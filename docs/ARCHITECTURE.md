# Architecture

This project is opinionated towards [Bun](https://bun.sh/) and renders on the server with TanStack Start and Nitro.

## Core Stack

- **Framework**: [TanStack Start](https://tanstack.com/start) — full-stack React with TanStack Router, server functions, and SSR.
- **Server**: [Nitro](https://nitro.unjs.io/) — handles server-side logic and deployment presets.
- **ORM & Database**: [Drizzle ORM](https://orm.drizzle.team/) with Bun's native SQL driver (`bun:sql` / `drizzle-orm/bun-sql`).
- **Auth**: [Better Auth](https://better-auth.com/) — email + password, email OTP, passkeys, and optional Google OAuth. Rate limited at the Better Auth layer (20 req/60 s).
- **Theme**: [next-themes](https://github.com/pacocoursey/next-themes) — class-based theme management on `html` with a mounted client toggle.

## Directory Structure

```
.
├── docs/
│   ├── ADDING-A-FEATURE.md # The schema-to-tests sequence for a new feature
│   ├── ARCHITECTURE.md   # This file
│   ├── CHANGELOG.md      # Release history
│   ├── CONTRIBUTING.md   # Branch, commit, and test conventions
│   ├── DEPLOYMENT.md     # Hosting options and platform config
│   ├── DESIGN.md         # Visual system notes
│   └── DEVELOPMENT.md    # Local setup, scripts, database, and testing guide
├── AGENTS.md             # Developer guide for agents (also CLAUDE.md)
├── CLAUDE.md             # Claude Code entry point — includes AGENTS.md
├── src/
│   ├── components/
│   │   ├── layout/       # Header and shell layout
│   │   ├── pages/        # Route-level page compositions
│   │   ├── providers/    # Client providers (theme)
│   │   └── ui/           # Reusable UI primitives
│   ├── db/               # Drizzle schema, client, and migrations
│   │   ├── drizzle/      # Generated SQL migrations (drizzle-kit)
│   │   ├── schema.ts     # notes table (with userId FK)
│   │   └── auth-schema.ts# Better Auth tables
│   ├── features/
│   │   ├── auth/         # Session/account server fns, query options, login/signup/OTP/reset forms
│   │   ├── emails/       # Email templates
│   │   ├── notes/        # Notes schema, server functions, and records.server
│   │   └── uploads/      # Upload schema, server function, and presign.server
│   ├── lib/              # Shared integrations and utilities
│   │   ├── auth-client.ts    # Better Auth React client
│   │   ├── auth.server.ts    # Better Auth server config
│   │   ├── logger.ts         # LogTape app logger and sink config
│   │   ├── mailer.server.ts  # Resend email sender (lazy init, optional)
│   │   ├── redis.server.ts   # Bun-native Redis client (optional)
│   │   ├── seo.ts            # SEO metadata, OpenGraph, structured data, crawler formats
│   │   ├── storage.server.ts # Bun-native S3-compatible upload client (optional)
│   │   └── utils.ts
│   ├── routes/           # TanStack Router routes and API handlers
│   │   ├── __root.tsx    # App shell
│   │   ├── _authenticated.tsx # Pathless layout route guarding authenticated pages
│   │   ├── _authenticated/
│   │   │   ├── dashboard.tsx # Protected route — notes CRUD, upload widget
│   │   │   └── settings.tsx  # Protected route — profile, providers, passkeys, delete account
│   │   ├── index.tsx     # Landing page
│   │   ├── login.tsx     # Auth route — redirects signed-in users
│   │   ├── signup.tsx    # Auth route — redirects signed-in users
│   │   ├── verify-otp.tsx
│   │   ├── reset-password.tsx # Request a reset link, or set a new password with ?token=
│   │   ├── sentry-example.tsx # Dev only
│   │   ├── robots[.]txt.ts   # Plain text crawler directives
│   │   ├── sitemap[.]xml.ts  # XML sitemap
│   │   └── api/
│   │       ├── auth/$.ts    # Better Auth handler
│   │       ├── health.ts
│   │       └── sentry-example.ts # Dev only
│   └── globals.css       # Global styles (Tailwind CSS v4)
├── tests/                # Vitest and Playwright suites
├── instrument.server.mjs # Server bootstrap — Sentry init and logging
├── components.json       # shadcn/ui configuration
├── Dockerfile
├── drizzle.config.ts
└── package.json
```

## Data Flow

1. **Routing**: Managed by TanStack Router. `src/routes/__root.tsx` composes the shell, theme provider, header, and page outlet.
2. **SSR**: TanStack Start handles the initial HTML render on the server via Nitro.
3. **Protected routes**: `src/routes/__root.tsx` resolves the session once per navigation and puts `{ user }` on the route context, which the header uses to render the signed-in nav on the server. The pathless `_authenticated.tsx` layout only refuses an unauthenticated visitor with a redirect to `/login` and re-emits the narrowed user for child routes (`dashboard.tsx`, `settings.tsx`). Auth routes (`/login`, `/signup`) redirect signed-in arrivals to `/dashboard`.
4. **Server functions**: `src/features/notes/server-fns.ts` exposes `listNotes`, `createNote`, and `deleteNote`, and `src/features/uploads/server-fns.ts` exposes `createUploadUrl`, all via `createServerFn`. Every function runs behind the middleware in `src/features/auth/session.ts`, which resolves the session. A refusal is a thrown `Error`, the behaviour TanStack Start documents: the caller catches it and reads `message`. The middleware's catch calls `setResponseStatus` first, so a direct HTTP caller still sees the status: 400 when the payload misses the schema, 401 without a session, 404 when the row is missing, 422 when the payload parses but the server refuses it, and 503 when a dependency is unconfigured.
5. **Query cache**: `src/router.tsx` creates one TanStack Query `QueryClient` per router (30s default `staleTime`) and `setupRouterSsrQueryIntegration` supplies the provider plus SSR dehydration/hydration. Route loaders prefetch with the same `queryOptions` objects their components read (`accountOptions` in `src/features/auth/accounts.ts`); mutations over loader-owned data call `router.invalidate()`.
6. **Auth flow**: Forms in `src/features/auth/components/*` call `src/lib/auth-client.ts`. `/login` supports email + password, email OTP, passkeys, and Google OAuth (when configured). `/signup` creates a password account (then holds the user on a "check your email" prompt) or sends an OTP; `/verify-otp` confirms the code and offers passkey enrollment; `/reset-password` both requests a reset link and consumes it (`?token=`).
7. **File uploads**: `createUploadUrl` in `src/features/uploads/server-fns.ts` validates the request through `src/features/uploads/schema.ts` and reaches `handleCreateUploadUrl` in `presign.server.ts` through a dynamic import. It presigns a `uploads/<userId>/<uuid>.<ext>` PUT URL and returns `{ url, key }`; the dashboard PUTs the file bytes straight to storage, so the server never proxies them. An unsupported content type or a file over 10 MB is a 422, and an unset `MINIO_ENDPOINT` is a 503.

## Database & Migrations

PostgreSQL is accessed using [Drizzle ORM](https://orm.drizzle.team/) paired with Bun's native SQL driver (`bun:sql` via `drizzle-orm/bun-sql`).

- **Schemas**: Defined in `src/db/schema.ts` (application tables such as `notes`) and `src/db/auth-schema.ts` (Better Auth tables: `user`, `session`, `account`, `verification`, `passkey`).
- **Migrations Directory**: Configured in `drizzle.config.ts` to output migrations to `src/db/drizzle/`.
- **Generating Migrations**: When schema files are updated, run `bun run db:generate` to produce timestamped SQL migration files and update the snapshot journal in `src/db/drizzle/meta/`. Never handwrite SQL migrations.
- **Applying Migrations**: Run `bun run db:migrate` to execute pending SQL migrations against the configured database (`DATABASE_URL`). For quick local development without migration tracking, `bun run db:push` can be used.

For developer commands, seeding, and local workflows, see the [Development Guide](./DEVELOPMENT.md#database-management--migrations).

## Authentication

Handled by **Better Auth**. Supported flows:

- **Email + password** — sign up and sign in with a password. The sign-up and reset forms share `PasswordSchema` (`src/features/auth/schema/password.ts`): 8–128 characters with at least one number and one symbol. That policy is client-side; Better Auth itself only enforces its 8-character minimum, so add a `before` hook on `/sign-up/email` and `/reset-password` if you need it enforced server-side too. Always available. Password hashes live in the existing `account.password` column, so no migration is involved. Sign-ups are stored with an empty `name`, matching what the email-OTP flow does, and are auto-signed-in (`requireEmailVerification` is off, so an unverified user can still sign in).
- **Email verification** — `emailVerification.sendOnSignUp` mails a link via the `VerificationEmail` template; Better Auth's own `/api/auth/verify-email` endpoint consumes it, so there is no app route for it. `/signup` shows a "check your email" prompt after a password sign-up rather than navigating away, because the window this closes is otherwise invisible: an email-OTP sign-in by an **unverified** user triggers Better Auth's `revokeUnprovenAccountAccess`, which deletes every account row and session that user has (its defence against someone registering a password on an address they do not own) — so an unverified password would be discarded the first time that user signs in with a code. Verified users keep their password across an OTP sign-in. Set `emailAndPassword.requireEmailVerification: true` if you would rather block sign-in until the link is clicked.
- **Password reset** — `/reset-password` sends a link (1 hour expiry) via `ResetPasswordEmail`. Better Auth's callback bounces the emailed link off `/api/auth/reset-password/:token` and back to `/reset-password?token=…`, or `?error=INVALID_TOKEN` when it has expired. Reset also _creates_ a credential account when the user has none, so OTP-only and Google-only users can adopt a password this way. It does not create a session; the user signs in afterwards.
- **Email OTP** — sign in and sign up via one-time code. Always available.
- **Passkeys** — register and authenticate with a device credential. Always available.
- **Google OAuth** — enabled only when `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set. The app boots and functions without them.

Rate limiting is configured at 20 requests per 60-second window using Better Auth's built-in `rateLimit` option.

## Styling

**Tailwind CSS v4** is integrated via `@tailwindcss/vite`. Theme switching is class-based on the `html` element through `next-themes`.

## Observability

### LogTape + Sentry

LogTape provides the app logger in `src/lib/logger.ts`. The server bootstrap (`instrument.server.mjs`) initialises Sentry with:

- `sendDefaultPii: false` — PII is not forwarded by default.
- `tracesSampleRate: 0.1` — 10% of server traces are sampled to control cost.

Enable `sendDefaultPii: true` and raise `tracesSampleRate` only intentionally, after reviewing your data-handling obligations.
