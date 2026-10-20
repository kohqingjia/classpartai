// oxlint-disable node/no-process-env
import { PostgreSqlContainer } from "@testcontainers/postgresql";
import type { StartedPostgreSqlContainer } from "@testcontainers/postgresql";
import { execFileSync } from "node:child_process";
import path from "node:path";
import { seed } from "../../scripts/seed";

let container: StartedPostgreSqlContainer | undefined;

/**
 * Spins up a postgres:18-alpine testcontainer, applies the committed migrations, and seeds test
 * data. Migrations rather than `drizzle-kit push`: generated SQL is what deploy runs, so the
 * suite has to exercise it.
 */
export async function setup(): Promise<void> {
  if (container) {
    return;
  }

  container = await new PostgreSqlContainer("postgres:18-alpine").start();
  const connectionUri = container.getConnectionUri();

  process.env.DATABASE_URL = connectionUri;
  // drizzle.config.ts imports src/env.ts, so the migration child process needs the full contract;
  // CI supplies the secret, local runs take the same throwaway one tests/setup.ts uses.
  process.env.BETTER_AUTH_SECRET ??= "01234567890123456789012345678901";
  process.env.BETTER_AUTH_URL ??= "http://localhost:3000";

  const drizzleBin = path.resolve(process.cwd(), "node_modules/drizzle-kit/bin.cjs");
  execFileSync(process.execPath, [drizzleBin, "migrate"], {
    env: {
      ...process.env,
      DATABASE_URL: connectionUri,
    },
    stdio: "inherit",
  });

  await seed(connectionUri);
}

/**
 * Stops the running PostgreSQL testcontainer.
 */
export async function teardown(): Promise<void> {
  if (container) {
    await container.stop();
    container = undefined;
  }
}

/**
 * Default export for Vitest globalSetup.
 */
export default async function (): Promise<() => Promise<void>> {
  await setup();
  return async () => {
    await teardown();
  };
}
