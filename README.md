# ClassPart AI

ClassPart AI is a classroom discussion application in development, built on TanStack Start, Better Auth, and Drizzle ORM. The current foundation includes authentication, account settings, demo notes, and file uploads. It runs on Bun-native APIs and drivers (`bun.SQL`, `Bun.s3`, `Bun.redis`).

## Features

- **SSR & Routing**: [TanStack Start](https://tanstack.com/start) with file-based routes and type-safe navigation.
- **Server Engine**: [Nitro](https://nitro.unjs.io/) for high-performance server-side logic.
- **Authentication**: [Better Auth](https://better-auth.com/) — email + password (with password-reset emails), email OTP, passkeys, and optional Google OAuth. Rate limited (20 req/60 s). Session-guarded protected routes and redirect logic included.
- **Database**: [Drizzle ORM](https://orm.drizzle.team/) with Bun's native SQL driver (`bun.SQL` / `drizzle-orm/bun-sql`).
- **Account management**: `/settings` route — profile, linked providers, passkeys, and account deletion via Better Auth.
- **File uploads**: An auth-guarded server function presigns PUT URLs with Bun's native S3 client (`Bun.s3`) for S3-compatible storage (MinIO locally; swap to AWS S3, Cloudflare R2, or Supabase Storage with an env var change).
- **Email**: Transactional email with [Resend](https://resend.com/) and [React Email](https://react.email/), or an SMTP relay via `SMTP_URL` for local and E2E runs. OTP, verification, and password-reset templates included.
- **Styling**: [Tailwind CSS v4](https://tailwindcss.com/)
- **Theme System**: Class-based light/dark switching via [next-themes](https://github.com/pacocoursey/next-themes).
- **Observability**: LogTape structured logging with a [Sentry](https://sentry.io/) sink. PII off by default, conservative sample rate. Debug routes gated to development.
- **Architecture**: Feature-based structure (`src/features`) with server-function data boundaries.
- **DX**:
  - [Oxlint](https://oxc.rs/docs/guide/usage/linter.html) & [Oxfmt](https://oxc.rs/docs/guide/usage/formatter.html) for fast linting and formatting.
  - [Playwright](https://playwright.dev/) for E2E tests in `tests/e2e/`.
  - [Vitest](https://vitest.dev/) for unit tests in `tests/unit/` and integration tests in `tests/integration/`.
  - [Lefthook](https://github.com/evilmartians/lefthook) for git hooks.
  - CI on GitHub Actions: lint, typecheck, format, migration drift, unit tests, integration tests, E2E, security checks, and a production build.

## Getting Started

### Prerequisites

- [Bun](https://bun.sh/) v1.4.2 (match `package.json` → `packageManager` exactly)
- Node.js 22.12+ (22 LTS) for Vitest/jsdom workers and tooling; Bun remains the application runtime.
- [Docker](https://www.docker.com/) for local services (Postgres, MinIO, Redis, Mailpit) and for the Testcontainers the integration and E2E suites start

### Setup

Clone the actual project repository:

```bash
git clone https://github.com/kohqingjia/classpartai.git
cd classpartai
```

If Bun is not on PATH, use the pinned runtime through npm:

```bash
npm exec --yes --package=bun@1.4.2 -- bun --version
npm exec --yes --package=bun@1.4.2 -- bun install --frozen-lockfile
```

For tooling when the installed Node is older than 22.12, use `npm exec --yes --package=bun@1.4.2 --package=node@22 -- bun run test:unit`.

Use the same `npm exec --yes --package=bun@1.4.2 --` prefix for every `bun` command below when using this fallback.

1. **Install dependencies**

   ```bash
   bun install --frozen-lockfile
   ```

2. **Configure environment**

   ```bash
   cp .env.example .env
   ```

   Replace `BETTER_AUTH_SECRET` with a unique secret of at least 32 characters. Local email goes to Mailpit; Google OAuth, Resend, and Sentry stay disabled until configured.

   Open `.env` and fill in the required values (see the [Environment Variables Reference](./docs/DEVELOPMENT.md#environment-variables) in the Development Guide).

3. **Start local services**

   ```bash
   docker compose up -d postgres redis minio minio_init mailpit
   ```

   This starts the infrastructure only; the app container binds port 3000 and would clash with the dev server. Mailpit captures the password-reset email for the E2E suite.

4. **Prepare the database**

   Apply migrations:

   ```bash
   bun run db:migrate
   ```

   _(Or push schema directly during local prototyping: `bun run db:push`)_

   Optionally seed with initial data:

   ```bash
   bun run db:seed
   ```

5. **Start the dev server**

   ```bash
   bun run dev
   ```

   Open [http://localhost:3000](http://localhost:3000). Sign up, sign in, and land on the protected dashboard.

For complete workflow instructions, script catalogs, testing guidelines, and environment configuration, see the [Development Guide](./docs/DEVELOPMENT.md).

## Local verification

With Docker running and port 3000 free:

```bash
docker compose ps
bun run lint:check
bun run type:check
bun run format:check
bun run test:unit
bun run test:integration
bun run build
bun run test:e2e
```

After `bun run dev`, verify the ClassPart AI title and professor landing page at `/`.
Create an account to enter the workspace immediately, without email verification. Confirm that notes persist
and **Settings** opens account management. View captured sign-in codes and password-reset emails at
[Mailpit](http://localhost:8025). The workspace currently offers notes and uploads;
class management, transcription, and AI analysis are planned.

If Docker reports it cannot connect, start Docker Desktop before starting services.
If MinIO image pulls are denied, the storage setup is blocked. To check the landing page,
authentication, notes, and settings independently, start the other services:

```bash
docker compose up -d postgres redis mailpit
```

Continue with migrations and the dev server. File uploads require resolving MinIO image
access and provisioning the storage bucket first.
A busy port 3000 usually means another dev server or the Compose app container is running;
stop that process before starting the app or browser tests.

## Deployment

The template ships a `Dockerfile` and `docker-compose.yaml` for containerised deployment.

```bash
docker build -t classpart-ai .
docker run -p 3000:3000 classpart-ai
```

## Documentation

- [Development](./docs/DEVELOPMENT.md) — local setup, scripts catalog, database management, testing, and tooling.
- [Adding a Feature](./docs/ADDING-A-FEATURE.md) — the schema-to-tests sequence for a new feature.
- [Architecture](./docs/ARCHITECTURE.md) — project structure, data flow, auth, and observability.
- [Design System](./docs/DESIGN.md) — aesthetic and design tokens.
- [Agents Guide](./AGENTS.md) — rules for coding agents working in this repo.
- [Deployment](./docs/DEPLOYMENT.md) — hosting options and platform-specific configuration.
- [Changelog](./docs/CHANGELOG.md) — version history.
- [Contributing](./docs/CONTRIBUTING.md) — branch, commit, and test conventions.

## Course evidence investigation

After applying migrations, sign in and select a session at `/assessments`. Course-passage search
uses PostgreSQL English full-text retrieval and works without an AI key. A bounded evidence agent
can choose searches, passage fetches and sufficient/gap completion through OpenAI Responses.
Configure server-only `OPENAI_API_KEY` privately in `.env`, restart the app, and follow the
[setup and evaluation guide](./docs/DEVELOPMENT.md#course-retrieval-and-evidence-agent-setup).
Optional `EVIDENCE_MODEL` defaults to `gpt-5.4-mini-2026-03-17`. Runs are persisted but executed
inside the HTTP request, not by a durable background worker. No participation scores or feedback
are produced by this slice; model-proposed support always requires professor review.
