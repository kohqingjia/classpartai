// oxlint-disable node/no-process-env, no-console, no-await-in-loop
import { execFileSync, spawn } from "node:child_process";
import type { ChildProcess } from "node:child_process";

import { PostgreSqlContainer } from "@testcontainers/postgresql";

import { seed } from "../../scripts/seed";

const APP_URL = "http://localhost:3000";

/**
 * Owns the whole E2E environment, in order: a postgres testcontainer on a random host port, the
 * committed migrations, the seed, then a fresh production build served on :3000 against that
 * database. Playwright runs this before the workers start and propagates `process.env` changes
 * to them, so the specs, the app, and this setup all share one `DATABASE_URL`. Every failure
 * throws instead of warning; teardown stops the server and the container, discarding the
 * database with it.
 */
export default async function globalSetup(): Promise<() => Promise<void>> {
  console.info("Spinning up PostgreSQL testcontainer for E2E tests...");
  const container = await new PostgreSqlContainer("postgres:18-alpine")
    .withUsername("postgres")
    .withPassword("postgres")
    .withDatabase("test")
    .start();
  const connectionUri = container.getConnectionUri();
  console.info(`E2E database ready at ${connectionUri}`);

  // drizzle.config.ts and the app both import src/env.ts; CI supplies the secret, local runs
  // take the same throwaway one tests/setup.ts uses.
  process.env.BETTER_AUTH_SECRET ??= "01234567890123456789012345678901";
  process.env.BETTER_AUTH_URL ??= "http://localhost:3000";
  // The password-reset journey reads its token out of the captured email; `docker compose up -d
  // mailpit` (or the CI service) is what serves this. Other specs do not need it.
  process.env.SMTP_URL ??= "smtp://127.0.0.1:1025";
  process.env.MAILPIT_URL ??= "http://localhost:8025";

  let server: ChildProcess | undefined;

  try {
    applyMigrations(connectionUri);
    await seed(connectionUri);
    process.env.DATABASE_URL = connectionUri;
    server = await startServer(connectionUri);
  } catch (error) {
    if (server) stopServer(server);
    await container.stop();
    throw error;
  }

  return async () => {
    if (server) stopServer(server);
    await container.stop();
  };
}

function applyMigrations(databaseUrl: string): void {
  execFileSync("bun", ["run", "db:migrate"], {
    env: { ...process.env, DATABASE_URL: databaseUrl },
    stdio: "inherit",
  });
}

async function startServer(databaseUrl: string): Promise<ChildProcess> {
  await assertAppPortFree();

  console.info("Building the app for the production server...");
  execFileSync("bun", ["run", "build"], { stdio: "inherit" });

  const server = spawn("bun", ["run", "start"], {
    env: { ...process.env, DATABASE_URL: databaseUrl, PORT: "3000" },
    stdio: "inherit",
    // A process group on POSIX so teardown can signal the whole tree; Windows uses taskkill /T.
    detached: process.platform !== "win32",
  });
  try {
    await waitForServer(server);
  } catch (error) {
    stopServer(server);
    throw error;
  }
  return server;
}

async function assertAppPortFree(): Promise<void> {
  try {
    await fetch(APP_URL, { signal: AbortSignal.timeout(1_000) });
  } catch {
    return;
  }
  throw new Error(`Something is already serving ${APP_URL}; stop it before running E2E tests.`);
}

async function waitForServer(server: ChildProcess): Promise<void> {
  let spawnError: Error | undefined;
  server.on("error", error => {
    spawnError = error;
  });

  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (spawnError) throw spawnError;
    if (server.exitCode !== null) {
      throw new Error(`Production server exited early with code ${server.exitCode}`);
    }
    try {
      const response = await fetch(APP_URL, { signal: AbortSignal.timeout(1_000) });
      if (response.status < 500) return;
    } catch {
      // Not accepting connections yet.
    }
    await new Promise(resolve => setTimeout(resolve, 250));
  }
  throw new Error(`Production server did not answer at ${APP_URL} within 30s`);
}

function stopServer(server: ChildProcess): void {
  if (server.pid === undefined) return;
  if (process.platform === "win32") {
    try {
      execFileSync("taskkill", ["/pid", String(server.pid), "/T", "/F"], { stdio: "ignore" });
    } catch {
      // The process already exited; nothing left to kill.
    }
  } else {
    try {
      process.kill(-server.pid, "SIGTERM");
    } catch {
      server.kill("SIGTERM");
    }
  }
}
