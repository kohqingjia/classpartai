# Development Guide

This guide covers the local development environment, scripts catalog, database management, testing practices, and code quality tooling for this project.

## Prerequisites

- **[Bun](https://bun.sh/)** v1.4.2 (match `package.json` → `packageManager` exactly)
- Node.js 22.12+ (22 LTS) for Vitest/jsdom workers and tooling; Bun remains the application runtime.
- **[Docker](https://www.docker.com/)** and Docker Compose: local PostgreSQL, MinIO, Redis, and Mailpit, plus the Testcontainers the integration and E2E suites start

## Local Setup

1. **Clone the repository and install dependencies**:

   ```bash
   bun install --frozen-lockfile
   ```

2. **Configure environment variables**:

   ```bash
   cp .env.example .env
   ```

   Replace `BETTER_AUTH_SECRET` with a unique secret of at least 32 characters. Defaults use local services and Mailpit for email; optional Google OAuth, Resend, and Sentry credentials are commented out until needed. See the pinned Bun fallback and local verification steps in [README.md](../README.md).

3. **Start local infrastructure services**:

   ```bash
   docker compose up -d postgres redis minio minio_init mailpit
   ```

   This starts infrastructure only, leaving port 3000 free for the dev server. This provisions:
   - **PostgreSQL 18** on `localhost:5432` (`app` database, user/password: `postgres`/`postgres`)
   - **MinIO S3** on `localhost:9000` (API) and `localhost:9001` (web console: `admin` / `password`)
   - **MinIO Init** bucket provisioner (`app` bucket created automatically)
   - **Redis 7** on `localhost:6379`
   - **Mailpit** on `localhost:1025` (SMTP) and `localhost:8025` (mail inbox)

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

## Trying the assessment input foundation

1. Use the pinned Bun 1.4.2 and the existing database setup, then run `bun run db:migrate`.
2. Start `bun run dev`, sign in normally, and open <http://localhost:3000/assessments> directly.
   Existing branding/navigation and authentication are unchanged.
3. Choose **Create a course from this file**, select
   `tests/fixtures/assessment-fictional.json`, and click **Import inputs**.
4. Inspect the combined roster, reviewed turns, rubric ranges, and source/page passages.
   The three students and professor are fictional; Student C has no observed contribution.
   The page generates no assessment. Imports persist across reloads; select a saved session
   to view it again. To add a session to a course, select that course before importing.
5. Real reviewed input follows the same documented fixture structure with provenance `reviewed`.
   The importing professor declares document authorisation. Roster IDs are not login IDs.
   For corrections, import a new snapshot; change rubric/document versions when their contents
   change. This first slice accepts reviewed JSON only, not raw audio or PDFs.

Development fixtures are neither seeded automatically nor available in production import/view
handlers. Keep development databases separate from production. No email or object storage is
needed for this foundation; their existing configuration is not verified by input imports.

## Course retrieval and evidence-agent setup

Use Bun 1.4.2 and Node 22 for the existing test workers. With PostgreSQL running:

```bash
bun run db:migrate
bun run dev
```

Sign in, open <http://localhost:3000/assessments>, import or select an existing session, and use
**Course evidence investigation** below the input viewer. JSON import remains the development
input path. Fictional fixture imports still require the dev server; production hides/rejects them.
Manual **Search passages** and **Fetch passage** work without a provider key.

To enable real model tool calls, edit the ignored local `.env` privately and set `OPENAI_API_KEY`
to your own OpenAI API credential with billing/model access. Never use a `VITE_` variable for it,
put it into JSON inputs, commit it, or paste it into logs/chat. Optional `EVIDENCE_MODEL` defaults
to `gpt-5.4-mini-2026-03-17`; the adapter uses strict Responses tools with reasoning effort `none`.
Restart the dev server after configuration changes. Provider/model access is not established by
having a ChatGPT subscription. Before investigation, confirm you may send the selected transcript,
rubric context and retrieved course text to this provider; the interface states what is sent.

Enter a question, select reviewed turns and rubric criteria, then click **Investigate evidence**.
With no key, a persisted failed run reports `provider_not_configured`; no canned evidence or
simulated model decision is substituted. With a key, inspect the run's actual tool activity,
validated arguments, references, budget usage, completion/gap reason and quotations. Check the
quotations' relevance and support yourself; a valid quotation does not establish a sound claim.
The HTTP request performs the work. Closing/restarting can interrupt it; stale runs are marked
failed on later inspection after 90 seconds. Retry by starting a new run, not by assuming a queued
row will run in the background. Provider failures may have unreported token usage.

Focused verification (Docker is required for integration and the normal production E2E harness):

```bash
bun run type:check
bun run lint:check
bun run format:check
bun run test:unit
bun run test:integration
bun run playwright test tests/e2e/assessments.test.ts tests/e2e/email-password-flow.test.ts
```

If the shell still has Node 20, prefix a test command with `npm exec --yes --package=node@22 --`.
Automated browser tests explicitly disable live provider calls. Agent-loop unit tests and the Bun
runtime harness use clearly labelled scripted/HTTP doubles, not evidence of live model agency.
The runtime harness verifies a completed run and JSONB object persistence using actual Bun SQL.

### Small live evaluation after configuring credentials

Use only the fictional development course. Select the relevant reviewed turn(s) and reasoning
criterion. Investigate each independently; do not force query counts or source order:

| Question                                                                             | What a professor should check                                                                                                                                    |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| What distinguishes an observation from an interpretation?                            | An exact, relevant citation to fictional handout A, page 1.                                                                                                      |
| How could a professor check an interpretation about a quiet student's understanding? | Whether context from handouts A and B supports the distinction and proposed check. A weak initial query may need reformulation; no specific trace is guaranteed. |
| What exact attendance penalty applies after three missed weeks?                      | The course sources do not supply that rule; a defensible result reports a gap rather than inventing a policy.                                                    |

Record actual tool names/queries, relevant quotations, conflicts, missing context, stop reason and
budget usage. Judge support/relevance as well as citation validity. Do not count a scripted test
trace as a live evaluation. Without credentials, all three live evaluations remain blocked.
