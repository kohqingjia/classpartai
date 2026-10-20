# TanStack Start Template

A production-ready full-stack web application template built with TanStack Start, Better Auth, and Drizzle ORM. It runs on Bun-native APIs and drivers (`bun.SQL`, `Bun.s3`, `Bun.redis`).

## Features

- **SSR & Routing**: [TanStack Start](https://tanstack.com/start) with file-based routes and type-safe navigation.
- **Server Engine**: [Nitro](https://nitro.unjs.io/) for high-performance server-side logic.
- **Authentication**: [Better Auth](https://better-auth.com/) — email + password (with reset and verification emails), email OTP, passkeys, and optional Google OAuth. Rate limited (20 req/60 s). Session-guarded protected routes and redirect logic included.
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

- [Bun](https://bun.sh/) v1.4.2 or later
- [Docker](https://www.docker.com/) for local services (Postgres, MinIO, Redis, Mailpit) and for the Testcontainers the integration and E2E suites start

### Setup

1. **Install dependencies**

   ```bash
   bun install
   ```

2. **Configure environment**

   ```bash
   cp .env.example .env
   ```

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

## Deployment

The template ships a `Dockerfile` and `docker-compose.yaml` for containerised deployment.

```bash
docker build -t tanstack-start-template .
docker run -p 3000:3000 tanstack-start-template
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
