import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "#": path.resolve(import.meta.dirname, "./src"),
      bun: path.resolve(import.meta.dirname, "./tests/shims/bun.ts"),
    },
  },
  test: {
    clearMocks: true,
    restoreMocks: true,
    coverage: {
      reporter: ["text", "json", "html"],
      enabled: true,
      // Measure the hand-written source tree only: generated files, vendored shadcn primitives,
      // and the bootstrap entrypoints are not what these tests exercise.
      include: [
        "src/*.{ts,tsx}",
        "src/components/**/*.{ts,tsx}",
        "src/db/**/*.{ts,tsx}",
        "src/features/**/*.{ts,tsx}",
        "src/hooks/**/*.{ts,tsx}",
        "src/lib/**/*.{ts,tsx}",
      ],
      exclude: [
        "**/*.d.ts",
        "src/components/ui/**",
        "src/db/drizzle/**",
        "src/routeTree.gen.ts",
        "src/router.tsx",
        "src/server.ts",
        "src/start.ts",
      ],
      // Baselines measured from the unit project, which is the coverage workhorse; the
      // integration project runs with coverage off (see `test:integration`) because a
      // boundary suite exercises little of the source tree by design.
      thresholds: {
        lines: 50,
        functions: 45,
        branches: 45,
        statements: 50,
      },
    },
    // A project that collected nothing is a wiring failure, not a pass.
    passWithNoTests: false,
    reporters: ["dot", "github-actions"],
    server: {
      deps: {
        inline: ["drizzle-orm"],
      },
    },
    projects: [
      {
        test: {
          name: "unit",
          include: ["tests/unit/**/*.{test,spec}.?(c|m)[jt]s?(x)"],
          environment: "jsdom",
          globals: true,
          setupFiles: [path.resolve(import.meta.dirname, "./tests/setup.ts")],
        },
      },
      {
        test: {
          name: "integration",
          include: ["tests/integration/**/*.{test,spec}.?(c|m)[jt]s?(x)"],
          environment: "node",
          globals: true,
          // One Postgres container shared by every file. Files that call `runSeed` and files
          // that delete or count the seed's rows cannot run at the same time without racing, so
          // the suite trades wall time for determinism.
          fileParallelism: false,
          setupFiles: [path.resolve(import.meta.dirname, "./tests/setup.ts")],
          globalSetup: "./tests/integration/integration-setup.ts",
          server: {
            deps: {
              // Inlined so `vi.mock` reaches inside it: the middleware runner reads TanStack
              // Start's async-local context, which a test supplies by mocking the storage module.
              inline: [
                /@tanstack\/react-start/,
                /@tanstack\/start-client-core/,
                /@tanstack\/start-storage-context/,
              ],
            },
          },
        },
      },
    ],
  },
});
