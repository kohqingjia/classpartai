# Development Guide

This guide covers the local development environment, scripts catalog, database management, testing practices, and code quality tooling for this project.

## Prerequisites

- **[Bun](https://bun.sh/)** v1.4.2 or later
- **[Docker](https://www.docker.com/)** and Docker Compose: local PostgreSQL, MinIO, Redis, and Mailpit, plus the Testcontainers the integration and E2E suites start

## Local Setup

1. **Clone the repository and install dependencies**:

   ```bash
   bun install
   ```

2. **Configure environment variables**:

   ```bash
   cp .env.example .env
   ```

   Inspect `.env` and fill in any optional credentials needed for your feature work (e.g. `GOOGLE_CLIENT_ID`, `RESEND_API_KEY`). Defaults for local services work out of the box.

3. **Start local infrastructure services**:

   ```bash
   docker compose up -d
   ```

   This provisions:
   - **PostgreSQL 18** on `localhost:5432` (`app` database, user/password: `postgres`/`postgres`)
   - **MinIO S3** on `localhost:9000` (API) and `localhost:9001` (web console: `admin` / `password`)
   - **MinIO Init** bucket provisioner (`app` bucket created automatically)
   - **Redis 7** on `localhost:6379`

4. **Prepare the database**:

   Run pending migrations to initialise tables:

   ```bash
   bun run db:migrate
   ```

   Optionally, seed sample records:

   ```bash
   bun run db:seed
   ```

5. **Start the local development server**:

   ```bash
   bun run dev
   ```

   The application starts on [http://localhost:3000](http://localhost:3000).

---

## Environment Variables

| Variable               | Required | Description                                                                                                                                              |
| ---------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `DATABASE_URL`         | ✅       | PostgreSQL connection string                                                                                                                             |
| `BETTER_AUTH_SECRET`   | ✅       | 32+ character secret for session signing                                                                                                                 |
| `BETTER_AUTH_URL`      | ✅       | App origin (default: `http://localhost:3000`)                                                                                                            |
| `SERVER_URL`           | Optional | Canonical public application URL                                                                                                                         |
| `GOOGLE_CLIENT_ID`     | Optional | Enables Google OAuth when set together with secret                                                                                                       |
| `GOOGLE_CLIENT_SECRET` | Optional | Enables Google OAuth when set together with ID                                                                                                           |
| `RESEND_API_KEY`       | Optional | Required to send email. App boots without it; email calls throw a clear error                                                                            |
| `EMAIL_FROM`           | Optional | Sender address (default: `onboarding@resend.dev`)                                                                                                        |
| `MINIO_ENDPOINT`       | Optional | S3-compatible endpoint — enables file uploads. Accepts MinIO, AWS S3, Cloudflare R2, or Supabase Storage (`https://<project>.supabase.co/storage/v1/s3`) |
| `MINIO_BUCKET`         | Optional | Bucket name (default: `app`)                                                                                                                             |
| `MINIO_ACCESS_KEY`     | Optional | Storage access key (default: `admin`)                                                                                                                    |
| `MINIO_SECRET_KEY`     | Optional | Storage secret key (default: `password`)                                                                                                                 |
| `REDIS_URL`            | Optional | Redis connection string (`redis://localhost:6379`) — enables Bun native Redis session cache for multi-instance deployments                               |
| `SENTRY_AUTH_TOKEN`    | Optional | Auth token for Sentry source map uploads at build time                                                                                                   |
| `VITE_APP_TITLE`       | Optional | Application title displayed in UI branding                                                                                                               |
| `VITE_SENTRY_DSN`      | Optional | Enables Sentry error tracking                                                                                                                            |
| `VITE_SENTRY_ORG`      | Optional | Sentry organization slug                                                                                                                                 |
| `VITE_SENTRY_PROJECT`  | Optional | Sentry project slug                                                                                                                                      |

---

## Scripts Catalog

All available scripts defined in `package.json`:

| Command                    | Description                                                            |
| -------------------------- | ---------------------------------------------------------------------- |
| `bun run dev`              | Start development server with SSR instrumentation on port 3000         |
| `bun run build`            | Build the application for production using Nitro and Vite              |
| `bun run build:docker`     | Build production Docker container image                                |
| `bun run preview`          | Preview production build locally                                       |
| `bun run start`            | Run production build server with Nitro and server instrumentation      |
| `bun run clean`            | Remove build artifacts, caches, coverage, and generated route trees    |
| `bun run type:check`       | Run TypeScript compiler check without emitting output (`tsc --noEmit`) |
| `bun run lint:check`       | Check code with Oxlint (denying warnings)                              |
| `bun run lint:fix`         | Automatically fix lint issues with Oxlint                              |
| `bun run format:check`     | Check code and doc formatting with Oxfmt                               |
| `bun run format:fix`       | Format files with Oxfmt                                                |
| `bun run auth:generate`    | Generate Better Auth schema components                                 |
| `bun run db:generate`      | Generate Drizzle SQL migration files from schema definitions           |
| `bun run db:migrate`       | Execute pending Drizzle migrations against `DATABASE_URL`              |
| `bun run db:push`          | Push schema directly to database (rapid prototyping only)              |
| `bun run db:pull`          | Introspect database schema into Drizzle definitions                    |
| `bun run db:seed`          | Run database seeding script (`scripts/seed.ts`)                        |
| `bun run db:studio`        | Launch Drizzle Studio web interface                                    |
| `bun run test`             | Run all Vitest test suites across projects                             |
| `bun run test:unit`        | Run unit tests (`tests/unit/`, `jsdom` environment)                    |
| `bun run test:integration` | Run integration tests (`tests/integration/`, `node` environment)       |
| `bun run test:e2e`         | Run Playwright end-to-end tests                                        |
| `bun run codegen`          | Launch Playwright code generator for browser test recording            |
| `bun run prepare`          | Install Lefthook git pre-commit hooks                                  |

---

## Database Management & Migrations

The project uses [Drizzle ORM](https://orm.drizzle.team/) with Bun's native SQL driver (`bun:sql` / `drizzle-orm/bun-sql`).

### Schema Locations

- `src/db/schema.ts` — Application domain schemas (e.g. `notes`).
- `src/db/auth-schema.ts` — Better Auth schemas (`user`, `session`, `account`, `verification`, `passkey`).
- `src/db/drizzle/` — Generated SQL migration files and metadata.

### Migration Rules

- **Always generate migrations**: Whenever modifying schema files, generate a new SQL migration:
  ```bash
  bun run db:generate
  ```
- **Never handwrite SQL migrations**: Drizzle Kit maintains schema snapshots in `src/db/drizzle/meta/`. Handwritten migrations will cause snapshot drift.
- **Commit schema and migrations together**: Always commit the schema modifications along with the resulting generated files in `src/db/drizzle/`.
- **Apply migrations**: Run `bun run db:migrate` to apply pending migrations.
- **Prototyping**: During early exploration, `bun run db:push` synchronises the schema directly without recording a migration file. Never use `db:push` in production.
- **Inspect data**: Run `bun run db:studio` to view and edit database rows via Drizzle Studio.

---

## Testing Guide

The test suite is structured into three tiers:

### 1. Unit Tests (`tests/unit/`)

- Configured under the `unit` project in `vitest.config.ts`.
- Uses `jsdom` environment with `@testing-library/react`.
- **Rule**: Unit tests must test pure logic and isolated components. They **must not** start a database container or rely on external network services.

Run unit tests:

```bash
bun run test:unit
```

### 2. Integration Tests (`tests/integration/`)

- Configured under the `integration` project in `vitest.config.ts`.
- Uses `node` environment.
- Tests database queries and service interactions using Testcontainers (`@testcontainers/postgresql`).

Run integration tests:

```bash
bun run test:integration
```

### 3. End-to-End Tests (`tests/e2e/`)

- Driven by Playwright (`playwright.config.ts`). There is no `webServer` config: `tests/e2e/global-setup.ts` starts a `postgres:18-alpine` testcontainer on a random port, applies the committed migrations, seeds it, builds the app, and serves production on :3000 against that database. Teardown stops the server and the container.
- Docker must be running and :3000 must be free; the setup fails on a busy port instead of reusing another server.
- Specs wait on hydration through `tests/e2e/hydration.ts`'s `waitForHydration`, which asserts `body[data-hydrated]`; do not wait on `networkidle`.
- The password-reset journey reads its token from the captured mail. Start Mailpit (`docker compose up -d mailpit`) so `SMTP_URL` (`smtp://127.0.0.1:1025`) has a server to relay to.

Run E2E tests:

```bash
bun run test:e2e
```

Run Playwright in interactive UI mode:

```bash
bunx playwright test --ui
```

### Running Targeted Tests

You can target specific test files or test names directly:

```bash
# Run a specific unit test file
bun run vitest run tests/unit/auth-session.test.ts

# Run a specific test case matching a pattern
bun run vitest run tests/unit/auth-session.test.ts -t "returns null"

# Run a specific E2E test file
bun run playwright test tests/e2e/landing.test.ts
```

---

## Code Quality & Git Hooks

### Linting & Formatting

- **[Oxlint](https://oxc.rs/docs/guide/usage/linter.html)**: Fast linter. Checks are enforced with `--deny-warnings`.
  ```bash
  bun run lint:check
  bun run lint:fix
  ```
  `jsPlugins` in `.oxlintrc.json` loads four ESLint plugins (TanStack Router, TanStack Query, Testing Library, Playwright) and the template's own house rules in `scripts/oxlint-plugin-template.js` (`template/*`). JS plugins run in a Node sidecar, so they are the slowest part of a lint run; add one only when it replaces a rule the built-in plugins cannot express.
- **[Oxfmt](https://oxc.rs/docs/guide/usage/formatter.html)**: Fast code and markdown formatter.
  ```bash
  bun run format:check
  bun run format:fix
  ```
- **TypeScript**:
  ```bash
  bun run type:check
  ```

### Pre-commit Hooks

[Lefthook](https://github.com/evilmartians/lefthook) runs automatically on `git commit`. It executes `oxlint --fix` and `oxfmt --write` against staged files:

```bash
bun run prepare # reinstalls hooks if needed
```

---

## Architecture & Code Conventions

For the full sequence that adds a feature across every layer, see [Adding a Feature](./ADDING-A-FEATURE.md).

### Server Functions & Bundle Isolation

Server functions created with `createServerFn` (TanStack Start) are imported by client routes. TanStack Start strips the `.handler(...)` bodies from client builds, but preserves all other code in the module.

- **Avoid module-level server imports**: Never import server-only dependencies (`#/db`, `"bun"`) at the top level if any exported helper references them (e.g. as a default parameter like `database = db`). This prevents Dead Code Elimination (DCE) and leaks server code into client bundles.
- **Use dynamic imports inside handlers**:
  ```ts
  const { db } = await import("#/db");
  ```
- **Import server types with `import type`**:
  ```ts
  import type { Database } from "#/db";
  ```
- **Do not use `.server.ts` naming for route-imported files**: `@tanstack/start-plugin-core` blocks files matching `**/*.server.*` from the client environment. The `.server.ts` suffix is reserved only for modules never imported by client routes.
- These rules are enforced by the `template/*` lint rules — `bundle-no-server-imports`, `bundle-no-server-default-params`, and `server-fn-requires-session` — so `bun run lint:check` fails on a violation instead of a later build or test run.

### Imports & Path Aliases

`#/*` is the sole alias for `src/*`. It is configured synchronously across:

- `tsconfig.json` (`paths`)
- `package.json` (`imports`)
- `vitest.config.ts` (`alias`)

Do not introduce alternate aliases without updating all three configuration files.

### Adding Environment Variables

When adding a new environment variable:

1. Declare and validate it in `src/env.ts` using `@t3-oss/env-core`. Keep it optional unless strictly required for bootstrap.
2. Add a commented entry with description and defaults in `.env.example`.
3. If it changes setup or prerequisites, document it in `README.md` and this guide.
