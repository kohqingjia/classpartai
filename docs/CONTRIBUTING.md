# Contributing

## Local Development

Before opening a pull request, ensure your local environment is configured and working. Follow the instructions in the [Development Guide](./DEVELOPMENT.md) for prerequisites, local service orchestration (Docker Compose), and the complete scripts catalog.

## Branches

- Base all work off `main`.
- Use short, lowercase, hyphen-separated names: `feat/notes-crud`, `fix/auth-redirect`, `chore/ci-cache`.

## Commits

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add notes CRUD to dashboard
fix: redirect signed-in users away from /login
chore: pin Bun version in CI
```

## Pre-PR Verification

Run the full verification suite before opening a PR:

```bash
bun run lint:check
bun run type:check
bun run format:check
bun run test:unit
bun run test:integration
bun run test:e2e
```

New features need at least one unit test covering the core behaviour. New routes need at least one Playwright smoke test verifying the happy path and any redirect guards. For detailed test tier rules and running targeted tests, see the [Testing Guide in DEVELOPMENT.md](./DEVELOPMENT.md#testing-guide).

## Database changes

When modifying database schemas (`src/db/schema.ts`, `src/db/auth-schema.ts`):

1. **Always generate migrations**: Run `bun run db:generate` to produce versioned migration SQL in `src/db/drizzle/`. Never handwrite SQL migrations.
2. **Commit both**: Commit schema changes together with the generated migration files.
3. **Verify migrations**: Run `bun run db:migrate` to verify they apply cleanly against your local database.

See [Database Management in DEVELOPMENT.md](./DEVELOPMENT.md#database-management--migrations) for full workflow details.

## Adding dependencies

Every runtime dependency added to `package.json` must be used by shipped code. Dev dependencies are fine as long as they stay out of the production bundle.

## Environment variables

All new env vars must be:

1. Added to `src/env.ts` (optional unless truly required for the app to boot).
2. Documented in `.env.example` with a descriptive comment.
3. Mentioned in `README.md` if they change the setup steps.
