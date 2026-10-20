/**
 * House rules for this template, enforced at lint time.
 *
 * These rules were unit tests that scanned the filesystem
 * (`client-bundle-safety`, `route-module-boundaries`, `server-function-middleware`). A lint rule
 * fails the same way — a red line on the offending file — but at the moment the code is written,
 * with the file and line in the message, and it costs one Node-sidecar pass instead of a Vitest
 * project. Each rule self-scopes by `context.filename`, so every rule here is enabled globally in
 * `.oxlintrc.json` and returns an empty visitor for files outside its directory.
 *
 * Keep in sync with:
 * - AGENTS.md ("File naming inside src/features/", "Server functions refuse by throwing an Error")
 * - docs/DEVELOPMENT.md#server-functions--bundle-isolation
 * - docs/ADDING-A-FEATURE.md (server functions, routes)
 */

/** `#/db`, `bun`, the database drivers, the auth runtime, and every module named `*.server`. */
const SERVER_ONLY_SPECIFIER =
  /^(?:#\/db(?:\/[^"']*)?|bun(?::[^"']*)?|drizzle-orm(?:\/[^"']*)?|postgres|pg|better-auth(?:\/(?!client|react|plugins\/access)[^"']*)?|resend|nodemailer(?:\/[^"']*)?|@tanstack\/react-start\/server(?:\/[^"']*)?|node:[^"']*|[^"']*\.server)$/;

/** React state and lifecycle hooks — a route module reaching for these is rendering, not routing. */
const VIEW_HOOKS = new Set([
  "useState",
  "useEffect",
  "useLayoutEffect",
  "useRef",
  "useMemo",
  "useCallback",
  "useReducer",
  "useTransition",
  "useImperativeHandle",
]);

/** The middleware that verifies (or deliberately tolerates) the session before a handler runs. */
const SESSION_MIDDLEWARE = new Set(["withSession", "requireSession"]);

/** Where a page view is allowed to live: a feature's components, or a static shared page. */
const VIEW_IMPORT = /^#\/features\/[^/]+\/components\/|^#\/components\/pages\//;

/** The route creators whose options object owns a `component` property. */
const ROUTE_CREATORS = new Set([
  "createFileRoute",
  "createRoute",
  "createRootRoute",
  "createRootRouteWithContext",
]);

/** `src/features` is the slice that carries server functions. */
const FEATURE_MODULE = /(^|\/)src\/features\//;
/** The client-reachable shared directories the client bundle must never pull server code from. */
const GUARDED_MODULE = /(^|\/)src\/(?:features|hooks|lib|components)\//;
const SERVER_MODULE = /\.server\.tsx?$/;
const ROUTE_MODULE = /(^|\/)src\/routes\//;

/** A file's path as the config writes it: forward slashes, no drive-letter surprises. */
function normalize(filename) {
  return filename.replace(/\\/g, "/");
}

function isGuardedModule(filename) {
  return GUARDED_MODULE.test(filename) && !SERVER_MODULE.test(filename);
}

function isRootRoute(filename) {
  return /(^|\/)__root\.tsx$/.test(filename);
}

/** Whether a static import or re-export of `source` would anchor a server runtime in the graph. */
function isServerOnlySpecifier(source) {
  return typeof source === "string" && SERVER_ONLY_SPECIFIER.test(source);
}

/** Skipping erased type-only imports and re-exports: `import type`, `export type`, `type` specifiers. */
function isTypeOnlyModule(node) {
  if (node.importKind === "type" || node.exportKind === "type") return true;

  const specifiers = node.specifiers ?? [];
  return (
    specifiers.length > 0 &&
    specifiers.every(s => s.importKind === "type" || s.exportKind === "type")
  );
}

/** The name an identifier, or the root of a member chain (`React.useState`), refers to. */
function rootIdentifierName(node) {
  let current = unwrap(node);

  while (current?.type === "MemberExpression") {
    current = unwrap(current.object);
  }

  return current?.type === "Identifier" ? current.name : undefined;
}

/** `ChainExpression`, `TSAsExpression`, `TSNonNullExpression`, and parens hide the node underneath. */
function unwrap(node) {
  let current = node;

  while (
    current &&
    (current.type === "ChainExpression" ||
      current.type === "TSAsExpression" ||
      current.type === "TSNonNullExpression" ||
      current.type === "ParenthesizedExpression")
  ) {
    current = current.expression;
  }

  return current;
}

/** Every `Identifier` referenced by `node`, without descending into nested functions or classes. */
function collectIdentifiers(node, names) {
  if (!node || typeof node !== "object") return;

  if (node.type === "Identifier") {
    names.add(node.name);
    return;
  }

  if (
    node.type === "FunctionExpression" ||
    node.type === "ArrowFunctionExpression" ||
    node.type === "FunctionDeclaration" ||
    node.type === "ClassExpression" ||
    node.type === "ClassDeclaration"
  ) {
    return;
  }

  for (const key of Object.keys(node)) {
    if (key === "parent" || key === "loc" || key === "range") continue;
    const value = node[key];
    if (Array.isArray(value)) {
      for (const item of value) collectIdentifiers(item, names);
    } else if (value && typeof value === "object") {
      collectIdentifiers(value, names);
    }
  }
}

/** The local names bound by a top-level value import of a server-only module. */
function serverImportedNames(program) {
  const names = new Set(["db"]);

  for (const statement of program.body) {
    if (statement.type !== "ImportDeclaration" || isTypeOnlyModule(statement)) continue;
    if (!isServerOnlySpecifier(statement.source?.value)) continue;

    for (const specifier of statement.specifiers) {
      const local = specifier.local?.name;
      if (local) names.add(local);
    }
  }

  return names;
}

/** The functions declared at the top level by a statement, exported or not. */
function declaredFunctions(statement) {
  const declaration = statement.declaration ?? statement;
  const functions = [];

  if (
    declaration.type === "FunctionDeclaration" ||
    declaration.type === "FunctionExpression" ||
    declaration.type === "ArrowFunctionExpression"
  ) {
    functions.push(declaration);
  }

  if (declaration.type === "VariableDeclaration") {
    for (const declarator of declaration.declarations) {
      const init = declarator.init;
      if (init?.type === "FunctionExpression" || init?.type === "ArrowFunctionExpression") {
        functions.push(init);
      }
    }
  }

  return functions;
}

/** A property named `component`, written as `component:`, `"component":`, or `["component"]:`. */
function isComponentProperty(node) {
  if (node.type !== "Property") return false;
  if (node.key?.type === "Identifier") return node.key.name === "component";
  if (node.key?.type === "Literal") return node.key.value === "component";
  return false;
}

/** Whether the property sits in the options object of a `createFileRoute(...)({ ... })` call. */
function isRouteOptionsProperty(node) {
  const object = node.parent;
  if (object?.type !== "ObjectExpression") return false;

  const call = unwrap(object.parent);
  if (call?.type !== "CallExpression" || unwrap(call.arguments[0]) !== object) return false;

  const callee = unwrap(call.callee);
  const creator = callee?.type === "CallExpression" ? unwrap(callee.callee) : callee;

  return creator?.type === "Identifier" && ROUTE_CREATORS.has(creator.name);
}

/** The `component: X` value is a reference into the file's import map, or it is view code. */
function componentReferenceName(value) {
  const expression = unwrap(value);
  if (expression?.type === "Identifier") return expression.name;
  if (expression?.type === "MemberExpression" && !expression.computed)
    return rootIdentifierName(expression);
  return undefined;
}

/** Whether `.middleware([...])` names session-enforcing middleware only. */
function isEnforcingMiddlewareArray(argument) {
  const array = unwrap(argument);
  if (array?.type !== "ArrayExpression" || array.elements.length === 0) return false;

  return array.elements.every(element => {
    const entry = unwrap(element);
    if (entry?.type === "Identifier") return SESSION_MIDDLEWARE.has(entry.name);
    if (entry?.type === "CallExpression")
      return SESSION_MIDDLEWARE.has(rootIdentifierName(entry.callee));
    return false;
  });
}

/**
 * The `.middleware(...)` calls between a `createServerFn(...)` call and its `.handler(...)`, read
 * off the member chain. `{ found, invalid }`: whether any `.middleware` call exists, and the calls
 * whose argument is not a non-empty array of enforcing middleware.
 */
function middlewareCalls(node) {
  const found = [];
  const invalid = [];
  let current = node;

  while (true) {
    const member = unwrap(current.parent);
    if (
      member?.type !== "MemberExpression" ||
      member.computed ||
      unwrap(member.object) !== current
    ) {
      break;
    }

    const call = unwrap(member.parent);
    if (call?.type !== "CallExpression" || unwrap(call.callee) !== member) break;

    const method = member.property?.name;
    if (method === "handler") break;
    if (method === "middleware") {
      found.push(call);
      if (!isEnforcingMiddlewareArray(call.arguments[0])) invalid.push(call);
    }

    current = call;
  }

  return { found, invalid };
}

/** The named declarations a top-level statement declares, by the name that binds each one. */
function topLevelDeclarations(statement) {
  const declaration = statement.declaration ?? statement;

  switch (declaration.type) {
    case "FunctionDeclaration":
    case "ClassDeclaration":
    case "TSInterfaceDeclaration":
    case "TSTypeAliasDeclaration":
    case "TSEnumDeclaration":
      return declaration.id?.name ? [{ node: declaration, name: declaration.id.name }] : [];
    case "VariableDeclaration":
      return declaration.declarations
        .filter(declarator => declarator.id?.type === "Identifier")
        .map(declarator => ({
          node: declarator.id,
          name: declarator.id.name,
        }));
    default:
      return [];
  }
}

const plugin = {
  meta: { name: "template" },
  rules: {
    /**
     * A client-reachable module must not statically import a server runtime. A static import is a
     * module-level reference the bundler cannot drop, so the dependency — and everything it pulls
     * in — is retained for the browser. `import type` and `await import(...)` inside a handler are
     * fine: the first is erased, the second is only reached on the server.
     */
    "bundle-no-server-imports": {
      meta: {
        type: "problem",
        docs: {
          description:
            "Disallow static imports of server-only modules from client-reachable modules",
        },
        messages: {
          serverImport:
            '`{{source}}` is server-only and must not be statically imported from a client-reachable module. Reach it with `await import(...)` inside `.handler()`, or move this module into a `*.server.ts` file. See docs/DEVELOPMENT.md, "Server Functions & Bundle Isolation".',
        },
      },
      create(context) {
        if (!isGuardedModule(normalize(context.filename))) return {};

        function check(node) {
          if (!node.source || !isServerOnlySpecifier(node.source.value)) return;
          if (isTypeOnlyModule(node)) return;

          context.report({
            node: node.source,
            messageId: "serverImport",
            data: { source: node.source.value },
          });
        }

        return {
          ImportDeclaration: check,
          ExportNamedDeclaration: check,
          ExportAllDeclaration: check,
        };
      },
    },

    /**
     * `export function listRows(database = db)` anchors the server dependency as a default
     * parameter, which keeps the import alive in the browser bundle even when the function is
     * never called there. The dependency belongs in the parameter list as a required argument.
     */
    "bundle-no-server-default-params": {
      meta: {
        type: "problem",
        docs: {
          description:
            "Disallow default parameters anchored on a server-only import in exported functions",
        },
        messages: {
          anchoredDefault:
            "`{{name}}` anchors a server-only binding as a default parameter, so the bundler cannot drop it. Take the dependency as a required parameter instead (see the injected `database` in src/features/notes/records.server.ts).",
        },
      },
      create(context) {
        if (!isGuardedModule(normalize(context.filename))) return {};

        return {
          Program(node) {
            const serverNames = serverImportedNames(node);

            for (const statement of node.body) {
              if (
                statement.type !== "ExportNamedDeclaration" &&
                statement.type !== "ExportDefaultDeclaration"
              ) {
                continue;
              }

              for (const fn of declaredFunctions(statement)) {
                for (const param of fn.params) {
                  const names = new Set();
                  collectIdentifiers(param, names);

                  const anchored = [...names].find(name => serverNames.has(name));
                  if (anchored) {
                    context.report({
                      node: param,
                      messageId: "anchoredDefault",
                      data: { name: anchored },
                    });
                  }
                }
              }
            }
          },
        };
      },
    },

    /**
     * A server function is a directly addressable HTTP route, so the session check has to live in
     * its middleware pipeline. Every chain under `src/features` must declare `.middleware([...])`
     * before `.handler(...)`, and every entry must be `requireSession` or `withSession`.
     */
    "server-fn-requires-session": {
      meta: {
        type: "problem",
        docs: {
          description: "Require session middleware on every server function under src/features",
        },
        messages: {
          missing:
            "Every `createServerFn` under src/features must run behind `requireSession` (or `withSession`) middleware. See docs/ADDING-A-FEATURE.md.",
          notEnforcing:
            "`.middleware` entries must all be `requireSession` or `withSession`; this array does not enforce the session.",
        },
      },
      create(context) {
        if (!FEATURE_MODULE.test(normalize(context.filename))) return {};

        return {
          CallExpression(node) {
            if (node.callee?.type !== "Identifier" || node.callee.name !== "createServerFn") return;

            const { found, invalid } = middlewareCalls(node);

            if (found.length === 0) {
              context.report({ node, messageId: "missing" });
              return;
            }

            for (const call of invalid) {
              context.report({ node: call, messageId: "notEnforcing" });
            }
          },
        };
      },
    },

    /**
     * Route modules are routing, and nothing else. A page that renders correctly renders correctly
     * wherever it is declared, so nothing else notices a view growing back into a route file —
     * except this rule.
     */
    "route-declaration-only": {
      meta: {
        type: "problem",
        docs: {
          description: "Disallow top-level declarations other than `Route` in route modules",
        },
        messages: {
          declaration:
            "Route modules declare `Route` and nothing else: move `{{name}}` into src/features/<feature>/components (or src/components/pages). See docs/ADDING-A-FEATURE.md.",
        },
      },
      create(context) {
        const filename = normalize(context.filename);
        if (!ROUTE_MODULE.test(filename) || !filename.endsWith(".tsx")) return {};

        return {
          Program(node) {
            for (const statement of node.body) {
              for (const { node: declared, name } of topLevelDeclarations(statement)) {
                if (name === "Route") continue;
                context.report({ node: declared, messageId: "declaration", data: { name } });
              }
            }
          },
        };
      },
    },

    /** React state and lifecycle in a route module means the module renders, not routes. */
    "route-no-view-hooks": {
      meta: {
        type: "problem",
        docs: { description: "Disallow React state and lifecycle hooks in route modules" },
        messages: {
          viewHook:
            "`{{name}}` renders, so it belongs in a component under src/features/<feature>/components, not in a route module.",
        },
      },
      create(context) {
        const filename = normalize(context.filename);
        if (!ROUTE_MODULE.test(filename) || !filename.endsWith(".tsx")) return {};

        return {
          CallExpression(node) {
            const callee = unwrap(node.callee);
            let name;

            if (callee?.type === "Identifier") {
              name = callee.name;
            } else if (callee?.type === "MemberExpression") {
              const property = unwrap(callee.property);
              name = !callee.computed
                ? property?.name
                : property?.type === "Literal" && typeof property.value === "string"
                  ? property.value
                  : undefined;
            }

            if (name && VIEW_HOOKS.has(name)) {
              context.report({ node: node.callee, messageId: "viewHook", data: { name } });
            }
          },
        };
      },
    },

    /**
     * `component:` names the view the route renders, and the view lives in the feature that owns
     * it (or in `src/components/pages` for static pages). Declaring one inline, or importing one
     * from the shared component library, is how a route file grows back into a page.
     */
    "route-view-source": {
      meta: {
        type: "problem",
        docs: {
          description: "Require route views to be imported from a feature or pages directory",
        },
        messages: {
          inline:
            "`component` must be a view imported from `#/features/<feature>/components` or `#/components/pages`, not declared in the route module.",
          unresolved:
            "`{{name}}` is not imported from `#/features/<feature>/components` or `#/components/pages`; a route renders a feature's view, not a local one.",
          shared:
            "Only `__root.tsx` may import `{{source}}`; shared components belong to a page under `#/components/pages` or to the feature that uses them.",
        },
      },
      create(context) {
        const filename = normalize(context.filename);
        if (!ROUTE_MODULE.test(filename)) return {};

        const isViewRoute = filename.endsWith(".tsx") && !isRootRoute(filename);
        const importedFrom = new Map();

        function sharedImport(node) {
          const source = node.source?.value;
          if (isRootRoute(filename) || typeof source !== "string") return;
          if (!source.startsWith("#/components/") || source.startsWith("#/components/pages/"))
            return;

          context.report({ node: node.source, messageId: "shared", data: { source } });
        }

        return {
          Program(node) {
            for (const statement of node.body) {
              if (statement.type !== "ImportDeclaration") continue;

              sharedImport(statement);

              for (const specifier of statement.specifiers) {
                if (specifier.local?.name) {
                  importedFrom.set(specifier.local.name, statement.source?.value);
                }
              }
            }
          },

          Property(node) {
            if (!isViewRoute || !isComponentProperty(node) || !isRouteOptionsProperty(node)) return;

            const name = componentReferenceName(node.value);
            if (!name) {
              context.report({ node, messageId: "inline" });
              return;
            }

            if (!VIEW_IMPORT.test(importedFrom.get(name) ?? "")) {
              context.report({ node: node.value, messageId: "unresolved", data: { name } });
            }
          },
        };
      },
    },
  },
};

export default plugin;
