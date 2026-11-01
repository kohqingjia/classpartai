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
6. **Auth flow**: Forms in `src/features/auth/components/*` call `src/lib/auth-client.ts`. `/login` supports email + password, email OTP, passkeys, and Google OAuth (when configured). `/signup` creates a password account (then opens the workspace) or sends an OTP; `/verify-otp` confirms the code and offers passkey enrollment; `/reset-password` both requests a reset link and consumes it (`?token=`).
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
- **Password registration** — no verification email is sent or required. Successful sign-up creates a session and opens `/dashboard` immediately. The email remains unverified; an optional email-OTP sign-in still follows Better Auth's ownership checks and may revoke an unverified credential account. Password-only sign-up and sign-in do not require email services. Password reset and email-code sign-in still use email.
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

## Participation assessment input foundation

Implemented: `/assessments` is an authenticated input import/viewer, not an AI assessment.
Existing Better Auth accounts act as professors by owning a course; there is no institution-wide
professor role or delegated teaching-team access yet. Every list/detail/import server function
requires a session. Database handlers filter by course `professorId`, including imports into an
existing course. Foreign and missing resources both return 404.

`courses` belongs to a professor account. `assessment_sessions` holds an immutable JSONB snapshot
of a complete reviewed input package (formatVersion 1). Snapshot-local roster IDs are independent
of login accounts and contain no delivery addresses. Reviewed turns have stable IDs, millisecond
start/end times and either professor attribution or a roster student ID. Rubric ID/version and
criterion score ranges are pinned with the snapshot. Documents include ID/version, source,
professor-declared course authorisation, and passages with stable IDs and positive page numbers.
No PDF parsing, storage fetching, embeddings or external retrieval occurs on import.

Validation rejects duplicate identifiers, unreviewed transcripts, invalid attribution, inverted
score ranges and malformed timestamps. Import is transactional and limited to 2 MB. Existing
course imports lock the course row, reject mixed fixture/real provenance and reject changed
rubrics/documents under the same ID/version. Corrections append a session snapshot; no update
or delete endpoint is exposed. JSONB is deliberately the smallest initial storage boundary;
normalise shared rosters/documents when editing and retrieval requirements justify it. There is
no claim that a roster member without a reviewed turn lacks understanding.

Fictional development inputs live only in `tests/fixtures/assessment-fictional.json`, never in
the default seed or public assets. Explicit development imports are labelled and stored under
separate courses. Production rejects fictional provenance and hides those snapshots even when
sharing a database with development. Authorisation is the professor's declaration, not a
copyright or institutional permission-verification service.

### Assessment boundaries

The evidence slice below now implements owner-scoped course passage search, citation fetch and a
bounded provider-backed evidence-agent loop. It does not assign scores. The coordinator and
rubric judge remain future integrations: observations must be distinguished from interpretation,
insufficient evidence must remain explicit, and feedback must cover every roster student.
Backend-controlled recipients and delivery will require professor approval of the exact feedback
version. No scores, feedback drafts or delivery workflow are implemented here.

## Course retrieval and bounded evidence investigation

Implemented: the selected `/assessments` snapshot now offers manual course search, passage fetch,
and a request-bound evidence investigation with persisted run history. No assessment score,
rubric judge, coordinator, feedback generator or delivery system is implemented by this slice.

### Sources and retrieval

`course_source_versions` deduplicates authorised material by course/document ID/version and a
SHA-256 digest of canonical source metadata and passage content. `course_passages` stores each
passage once per version, with a stable database ID, imported passage key, source and page.
`assessment_session_sources` links a snapshot to exactly the source versions it imported.
Imports create these links transactionally. Existing snapshots are indexed lazily only after
ownership checks, without mutating their inputs. The original JSON input contract still embeds
source content for reproducibility and compatibility; it has not been replaced by a new editor
or a reference-only import format. Retrieval indexing itself does not duplicate source content
for each session. A later import-format version may reference existing immutable versions.

Search uses PostgreSQL English `to_tsvector`/`websearch_to_tsquery` with a GIN expression index,
ordered by `ts_rank_cd`. This is lexical retrieval with stemming, not embedding/semantic search.
Paraphrases, non-English text, domain terminology and synonyms may miss; empty results do not
prove source absence. Search accepts at most 240 characters and returns at most five previews
of 1,200 characters. Fetch returns at most 6,000 characters starting at a bounded offset.
Previews can omit a later match; the model may fetch more context. Rank order is not certainty.

Every retrieval SQL query joins session, source links and course, checks professor ownership
and source/course consistency, and enforces development-fixture visibility. The model cannot
supply a professor or course identity. Trusted context binds it to one authorised session.
Only document ID/version filters and passage IDs within that scope are accepted. Text is
parameterised in SQL. No internet retrieval or arbitrary URL fetching tool is available.

### Provider, decisions and budgets

The server-only adapter uses OpenAI Responses HTTP function calling through built-in `fetch`;
no model SDK, agent framework, vector database or separate service was added. Default model:
`gpt-5.4-mini-2026-03-17`, with `reasoning.effort: none`, strict tools and `store: false`.
See [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
and [the model contract](https://developers.openai.com/api/docs/models/gpt-5.4-mini).
`OPENAI_API_KEY` and optional `EVIDENCE_MODEL` are server-only configuration. Alternative models
must support Responses strict function calling and the configured reasoning option; availability
is account-dependent. No hidden reasoning or raw provider response is persisted or displayed.

The model chooses `search_course_passages`, `get_source_passage`, or `finish_evidence` on each
iteration. It chooses query wording, reformulations, filters, passage windows, further retrieval
for conflicts, quotations, relevance explanations, and sufficient-vs-gap completion. A gap can
finish without a mandatory search sequence. The backend never scripts a query/source route.
Tool calls, malformed arguments and invalid citation attempts consume the same budget.
Limits: eight model calls, eight tool calls (including finish), 60,000 cumulative reported tokens,
2,000 output tokens per response, 36,000 returned source characters including metadata, 50,000
history UTF-8 bytes, 128,000 provider-response bytes and a 90-second execution deadline.
Before each request, total payload UTF-8 bytes plus output cap conservatively bound remaining
tokens. Actual reported usage is recorded; failed network calls may have unreported billable
usage. There are no automatic provider retries. Backend queries can finish after a cancelled
request, but no further model/tool decisions are accepted past the execution deadline.

Transcripts, rubric descriptions, questions and retrieved text are untrusted data in the model
context. System instructions explicitly prevent them changing the goal, tools, permissions or
approval rules. These prompt instructions complement backend allowlists, strict argument schemas,
course-scoped SQL, budgets and citation checks; they are not a guarantee of perfect relevance
or immunity to misleading text. No prompt can enable email, scoring, execution or internet tools.

### Persisted execution and interruptions

`evidence_runs` records request/context IDs, snapshot/source versions and digests, model, prompt
version, budgets, progress, final bundle, stop reason and deadline. Status progresses from queued
(request startup) to running, then completed, needs_review or failed. Each model attempt and tool
activity is checkpointed, with validated arguments, result references and a concise public action
summary. Raw malformed arguments, provider error bodies and hidden chain-of-thought are not saved.
JSONB writes preserve the Bun/Drizzle fix: bind JSON as text, then cast to JSONB.

This is an awaited HTTP request, **not a durable background job**. There is no worker, retry queue,
or resume-on-restart claim. One active request per session is allowed. Disconnects/timeouts stop
further decisions when the request signal is delivered. A process crash can leave a queued/running
row; the next history read or start marks it failed once its deadline has elapsed. Before that,
the row still reports active. A late request cannot overwrite a reconciled terminal run. Retry
means explicitly starting a new run identity; old history is retained. Hosting environments with
short HTTP limits need a durable worker before supporting longer investigations.

### Evidence bundle contract for a future rubric judge

The concrete TypeScript contract is `EvidenceBundle` in `src/features/evidence/schema.ts`:

- `contractVersion: 1`, `sessionId`, exact investigated `question`, `transcriptVersion`.
- `rubric: { id, version, criterionIds }` and relevant supplied `turnIds`.
- `status: sufficient | gap`, short `explanation`, `conflicts`, and explicit unresolved `gaps`.
- Citations: authorised retrieved `passageId`, imported `documentId`/`version`, `passageKey`,
  `title`, `source`, `page`, exact `excerpt`, model-proposed `relevance` and relationship
  (`supports`, `conflicts`, or `context`). Run manifests additionally pin source content digests.
- `citationValidity: authorised_retrieved_exact_excerpt` means the IDs and returned quotation
  windows passed mechanical validation. It does **not** establish support, completeness or truth.
- `supportValidation: model_proposed_professor_review_required` is always retained. Completion
  denotes investigation completion, never a final participation assessment or professor approval.

The judge must consume a backend-loaded run with its pinned snapshot, not trust a client-supplied
bundle, and preserve session/roster IDs, transcript version/turn IDs, rubric ID/version/criterion
IDs and exact document/version/passage/page references. Gaps and conflicts must remain visible;
insufficient evidence is distinct from a low score. Evidence is not a new source of instructions.

Later coordinator tools (contracts only, no fake implementations):

| Tool                         | Intended boundary                                                                                                                       |
| ---------------------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| `inspect_transcript_context` | Read reviewed turns and neighbouring context by stable IDs; keep uncertain attribution explicit.                                        |
| `retrieve_evidence`          | Invoke this evidence investigation and return its validated bundle, gaps and run ID.                                                    |
| `propose_rubric_assessment`  | Propose criterion scores within the pinned rubric, with observations separated from interpretation and an insufficient-evidence option. |
| `audit_assessment`           | Check coverage, citations, contradictions, score ranges and uncertainty; return specific revision needs.                                |
| `draft_feedback`             | Prepare provisional personalised drafts for every roster student, including no-observed-contribution cases.                             |
| `request_professor_review`   | Present the exact version for approval; do not infer approval from a draft or model completion.                                         |

A future coordinator chooses actions dynamically from persisted progress and results; it does not
invoke all tools in a mandatory sequence. Changes to drafts invalidate affected approvals. Only
the backend may resolve roster recipients and send the exact approved feedback version, with
idempotent delivery and development test recipients. No observed contribution is not proof of
poor understanding. Those approval/delivery invariants are requirements, not implemented features.
