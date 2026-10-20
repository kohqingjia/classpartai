import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

/**
 * The house rules in `scripts/oxlint-plugin-template.js` replaced the filesystem-scanning unit
 * tests (`client-bundle-safety`, `route-module-boundaries`, `server-function-middleware`), so this
 * suite drives the real binary over fixture trees: it proves the plugin loads, every rule fires on
 * the violation it exists for, and none of them fire on the shape the template actually writes.
 *
 * `RuleTester` from `oxlint/plugins-dev` would assert the rules in-process, but it throws under Bun
 * ("Raw transfer is not supported on Bun"), and this repo runs Vitest under Bun.
 *
 * The fixtures are written to the OS temp directory so `oxlint .` in the repo never sees them, and
 * the whole tree is linted in one invocation: one Node sidecar start, six rules exercised.
 */
const ROOT = path.resolve(import.meta.dirname, "../..");
const PLUGIN = path.join(ROOT, "scripts/oxlint-plugin-template.js");
const OXLINT_BIN = path.join(ROOT, "node_modules/oxlint/bin/oxlint");

const RULES = [
  "template/bundle-no-server-imports",
  "template/bundle-no-server-default-params",
  "template/server-fn-requires-session",
  "template/route-declaration-only",
  "template/route-no-view-hooks",
  "template/route-view-source",
];

/** Lint a fixture tree with only the house rules enabled; return the diagnostics. */
function lint(files: Record<string, string>): string[] {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "template-plugin-"));

  try {
    for (const [relative, content] of Object.entries(files)) {
      const target = path.join(dir, relative);
      fs.mkdirSync(path.dirname(target), { recursive: true });
      fs.writeFileSync(target, content);
    }

    const config = path.join(dir, ".oxlintrc.json");
    fs.writeFileSync(
      config,
      JSON.stringify({
        jsPlugins: [PLUGIN.replace(/\\/g, "/")],
        rules: Object.fromEntries(RULES.map(rule => [rule, "error"])),
      })
    );

    try {
      execFileSync(process.execPath, [OXLINT_BIN, "-c", config, "."], {
        cwd: dir,
        encoding: "utf8",
        stdio: "pipe",
      });
      return [];
    } catch (error) {
      const failure = error as { stdout?: string; stderr?: string };
      const stderr = failure.stderr ?? "";
      if (stderr.includes("JS plugin")) {
        throw new Error(`oxlint failed to run the plugin: ${stderr}`, { cause: error });
      }

      return (failure.stdout ?? "").split("\n").filter(Boolean);
    }
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
}

const violations: Record<string, string> = {
  "src/features/leaky/imports.ts": [
    'import { db } from "#/db";',
    'export { notes } from "#/db/schema";',
    'export * from "#/db";',
    'import "./records.server";',
    'import { sql } from "drizzle-orm";',
    "export const rows = Object.values({ db, notes, sql });",
  ].join("\n"),

  "src/features/leaky/defaults.ts": [
    'import { db } from "#/db";',
    "export function listRows(database = db) {",
    "  return database;",
    "}",
    "export const countRows = async (database = db) => database;",
    "function localOnly(database = db) {",
    "  return database;",
    "}",
  ].join("\n"),

  // A mixed `type` + value import still reaches the module at runtime, so it is flagged like any
  // other value import.
  "src/features/leaky/mixed.ts": [
    'import { type Database, db } from "#/db";',
    "export const handle = (database: Database) => db ?? database;",
  ].join("\n"),

  "src/features/unguarded/server-fns.ts": [
    'import { createServerFn } from "@tanstack/react-start";',
    'export const a = createServerFn({ method: "GET" }).handler(() => null);',
    "export const b = createServerFn().middleware([]).handler(() => null);",
    "export const c = createServerFn<{ id: string }>().middleware([requireSession]).handler(() => null);",
  ].join("\n"),

  "src/routes/bad.tsx": [
    'import { createFileRoute } from "@tanstack/react-router";',
    'import { useState } from "react";',
    'import { Header } from "#/components/layout/header";',
    "const helper = () => useState(0);",
    'export const Route = createFileRoute("/bad")({ component: () => <div>{helper()}</div> });',
    "export const shared = Header;",
  ].join("\n"),

  "src/routes/unverified.tsx": [
    'import { createFileRoute } from "@tanstack/react-router";',
    "const LocalView = () => <p>hi</p>;",
    'export const Route = createFileRoute("/unverified")({ component: LocalView });',
  ].join("\n"),
};

const clean: Record<string, string> = {
  // A compliant server function: enforcing middleware, dependencies reached inside the handler,
  // and the server-only module allowed to import the server-only ones.
  "src/features/clean/server-fns.ts": [
    'import { createServerFn } from "@tanstack/react-start";',
    'import type { SessionUser } from "#/features/auth/session";',
    'export const list = createServerFn({ method: "GET" })',
    "  .middleware([requireSession])",
    "  .handler(async ({ context }: { context: { user: SessionUser } }) => {",
    '    const { db } = await import("#/db");',
    '    const { rows } = await import("./rows.server");',
    "    return { db, rows, user: context.user };",
    "  });",
  ].join("\n"),

  "src/features/clean/rows.server.ts": [
    'import { db } from "#/db";',
    "export const rows = [db];",
  ].join("\n"),

  // A required, injected database parameter is the shape the rules push you toward.
  "src/features/clean/defaults.ts": [
    'import type { Database } from "#/db";',
    "export function listRows(database: Database) {",
    "  return database;",
    "}",
  ].join("\n"),

  // A thin route: only `Route`, a feature view, and a validate/loader/head order the router
  // plugin accepts.
  "src/routes/good.tsx": [
    'import { createFileRoute } from "@tanstack/react-router";',
    'import { DashboardPage } from "#/features/dashboard/components/page";',
    'export const Route = createFileRoute("/good")({',
    "  validateSearch: (search: Record<string, unknown>) => search,",
    "  loader: async () => ({ ready: true }),",
    "  head: () => ({ meta: [] }),",
    "  component: DashboardPage,",
    "});",
  ].join("\n"),

  // Type-only import: erased before the bundler sees it.
  "src/features/clean/types.ts": [
    'import type { Database } from "#/db";',
    'export type { Database as Db } from "#/db";',
    "export function pick(database: Database) {",
    "  return database;",
    "}",
  ].join("\n"),

  // A static import after the route declaration still resolves the `component:` value; the rule
  // reads the whole module, not the statements it has already passed.
  "src/routes/late-import.tsx": [
    'import { createFileRoute } from "@tanstack/react-router";',
    'export const Route = createFileRoute("/late")({ component: LandingPage });',
    'import { LandingPage } from "#/components/pages/landing";',
  ].join("\n"),
};

describe("template house rules", () => {
  const diagnostics = lint({ ...violations, ...clean }).map(line => line.replace(/\\/g, "/"));

  it.each([
    ["src/features/leaky/imports.ts", "bundle-no-server-imports"],
    ["src/features/leaky/mixed.ts", "bundle-no-server-imports"],
    ["src/features/leaky/defaults.ts", "bundle-no-server-default-params"],
    ["src/features/unguarded/server-fns.ts", "server-fn-requires-session"],
    ["src/routes/bad.tsx", "route-declaration-only"],
    ["src/routes/bad.tsx", "route-no-view-hooks"],
    ["src/routes/bad.tsx", "route-view-source"],
    ["src/routes/unverified.tsx", "route-view-source"],
  ])("flags %s with template/%s", (file, rule) => {
    expect(diagnostics.some(line => line.includes(file) && line.includes(rule))).toBe(true);
  });

  it("leaves the compliant shapes alone", () => {
    const offenders = diagnostics.filter(
      line =>
        line.includes("/clean/") || line.includes("good.tsx") || line.includes("late-import.tsx")
    );

    expect(offenders).toEqual([]);
  });

  it("reports the guard drops a non-exported default parameter", () => {
    const flagged = diagnostics.filter(
      line => line.includes("src/features/leaky/defaults.ts") && line.includes("default-params")
    );

    // `listRows` and `countRows` are exported, `localOnly` is not — the retired test drew the
    // same line.
    expect(flagged).toHaveLength(2);
  });

  it("reports every unguarded server function", () => {
    const flagged = diagnostics.filter(line =>
      line.includes("src/features/unguarded/server-fns.ts")
    );

    // `a` has no middleware, `b` runs an empty array; `c` is guarded and generic.
    expect(flagged).toHaveLength(2);
  });

  it("keeps the rules enabled in the repo config", () => {
    const config = fs.readFileSync(path.join(ROOT, ".oxlintrc.json"), "utf8");

    expect(config).toContain("./scripts/oxlint-plugin-template.js");
    for (const rule of RULES) {
      expect(config).toContain(`"${rule}": "error"`);
    }
  });
});
