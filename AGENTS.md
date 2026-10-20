# AGENTS.md

This file provides guidance to AI agents when working with code in this repository.

## Where things are documented

Read these instead of re-deriving; do not duplicate their content here.

- `docs/ARCHITECTURE.md` — stack, directory map, data flow, auth flows, observability config.
- `docs/DEVELOPMENT.md` — local setup, environment variables, scripts, database workflows, testing, and tooling.
- `docs/CONTRIBUTING.md` — branch names, Conventional Commits, dependency and env-var rules.
- `README.md` — overview, quickstart, local services.

## Running a single test

`package.json` only exposes whole-suite scripts; target a single test by passing the path through:

```bash
bun run vitest run tests/unit/auth-session.test.ts            # one file
bun run vitest run tests/unit/auth-session.test.ts -t "returns null"   # one case
bun run playwright test tests/e2e/landing.test.ts     # one E2E file
```

## Test layout gotchas

- `test:unit` runs the Vitest `unit` project (`vitest run --project unit`), targeting `tests/unit/` with `jsdom` environment.
- `test:integration` runs the Vitest `integration` project (`vitest run --project integration`), targeting `tests/integration/` with `node` environment.
- Unit tests must not start a database container; keep them to pure logic. Testcontainers belongs in integration/E2E only.
- Coverage is `enabled: true` in `vitest.config.ts`, so test runs rewrite `coverage/`.

## Lint house rules

Structural rules about where code may live are Oxlint rules, not tests: `scripts/oxlint-plugin-template.js` defines the `template/*` rules (`bundle-*`, `server-fn-*`, `route-*`), each of which scopes itself by path. `.oxlintrc.json` also loads the TanStack Router/Query and Testing Library/Playwright ESLint plugins through `jsPlugins`. When one of these rules fires, fix the code rather than disabling the rule; `// oxlint-disable-next-line <rule>` is the last resort and needs a reason in the comment.

## File naming inside `src/features/`

- Server functions exported via `createServerFn` and consumed by routes are compiled for the client environment. TanStack Start strips `.handler(...)` bodies but preserves all other `export` declarations.
- Never statically import runtime built-ins or server-only dependencies (`#/db`, `"bun"`) at module level if any exported helper references them (e.g. via default parameters like `database = db`). This anchors the dependency in the AST and prevents Dead Code Elimination, leaking server built-ins into client bundles.
- Instead, reach server dependencies dynamically inside `.handler()` via `await import("#/db")`, import server types with `import type`, and require injected dependencies in exported helpers (e.g. `database: Database`).
- Do **not** name either kind `<feature>.server.ts`. `@tanstack/start-plugin-core`'s import-protection plugin denies `**/*.server.*` in the client environment, so the first route that imports it fails `bun run build`; the lint rule `template/bundle-no-server-imports` also flags a static `.server` import from the shared directories it scans. That suffix is only for modules nothing client-reachable imports.
- No `-model` suffix, and no entity-name stutter (`notes/notes-fns.ts`). A helper with only one caller lives in that caller's file — even if a unit test also imports and tests it (export it from the caller's file for the test). Only extract a helper into its own file when it has two or more application callers.
- Server-function validation lives in the Zod schema, parsed with `safeParse` rethrowing `issues[0].message` — never let a raw `ZodError` reach a route.
- Server functions refuse by throwing an `Error` (the status-carrying classes in `src/features/auth/session.ts`). The session middleware calls `setResponseStatus` with the matching code and rethrows, so a direct HTTP caller sees 400/401/404/422/503 while an in-app caller catches the error and reads `message`. Never return or throw a `Response` for a refusal: since TanStack Start 1.169 the call rejects with whatever was thrown, so a `Response` would reach the caller in place of the typed error.

## Imports

`#/...` is the only alias for `src/`. It is declared in three places that must stay in sync — `tsconfig.json` `paths`, `package.json` `imports`, and the `alias` block in `vitest.config.ts` — so adding another alias means touching all three or it will typecheck and then fail under test. `components.json` already generates `#/`, so shadcn output needs no rewriting.

## Adding an environment variable

Three places, all required: `src/env.ts`, a commented entry in `.env.example`, and `README.md` if it changes setup steps.

## Database schemas and migrations

- Whenever touching or modifying database schemas (`src/db/schema.ts`, `src/db/auth-schema.ts`, or any schema definition file), **always run `bun run db:generate`** to generate the corresponding migration SQL files in `src/db/drizzle/`.
- **Never handwrite SQL migrations**. All migrations must be generated by Drizzle Kit from schema definitions to maintain consistency and prevent schema drift.
- Review generated migration files in `src/db/drizzle/` to verify that the generated DDL statements accurately reflect the schema changes.
- To apply pending migrations to the database, run `bun run db:migrate` (or `bun run db:push` for local rapid prototyping).
