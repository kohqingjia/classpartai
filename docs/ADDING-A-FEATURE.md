# Adding a Feature

A feature runs through five layers: a schema, server-only record handlers, a server function, a route with its view, and tests. This guide walks the notes feature end to end; copy its shape for a new domain.

## 1. Add the schema

Add the table to `src/db/schema.ts`. The notes table shows the shape: a primary key, the payload, a `userId` foreign key to Better Auth's `user` table, and a timestamp.

```ts
export const notes = pgTable("notes", {
  id: serial("id").primaryKey(),
  title: text("title").notNull(),
  userId: text("user_id")
    .notNull()
    .references(() => user.id, { onDelete: "cascade" }),
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow(),
});
```

Generate the migration and apply it. The repository rules are in [Database schemas and migrations](../AGENTS.md#database-schemas-and-migrations) and [Database Management & Migrations](./DEVELOPMENT.md#database-management--migrations).

```bash
bun run db:generate
bun run db:migrate
```

## 2. Define the input schema

Create `src/features/<feature>/schema.ts` with the Zod schema and a parser. The parser throws a `ValidationError` (400) carrying `issues[0].message`, so the route or toast shows one sentence instead of Zod's JSON dump.

```ts
import { z } from "zod";

import { ValidationError } from "#/features/auth/session";

export const CreateNoteInput = z.object({
  title: z
    .string()
    .trim()
    .min(1, "Title is required")
    .max(255, "Title must be 255 characters or fewer"),
});

export function parseCreateNote(data: unknown) {
  const parsed = CreateNoteInput.safeParse(data);
  if (!parsed.success) throw new ValidationError(parsed.error.issues[0].message);
  return parsed.data;
}
```

## 3. Write the record handlers

Create `src/features/<feature>/records.server.ts`. The `.server.ts` suffix marks a module that nothing client-reachable imports; `server-fns.ts` reaches it through a dynamic `import()`. The handlers take the session user and the database as parameters, so integration tests can pass a Testcontainers connection.

```ts
import { eq, desc } from "drizzle-orm";
import type { db as Db } from "#/db";
import { notes } from "#/db/schema";
import type { SessionUser } from "#/features/auth/session";
import { parseCreateNote } from "#/features/notes/schema";

type Database = typeof Db;

export async function handleListNotes(user: SessionUser, database: Database) {
  return database
    .select()
    .from(notes)
    .where(eq(notes.userId, user.id))
    .orderBy(desc(notes.createdAt));
}

export async function handleCreateNote(data: unknown, user: SessionUser, database: Database) {
  const { title } = parseCreateNote(data);
  const [note] = await database.insert(notes).values({ title, userId: user.id }).returning();
  return note;
}
```

A handler that cannot find its row throws `NotFoundError`; the session middleware sets the 404 on the response and rethrows, which is what a direct HTTP caller and an in-app caller each observe. `ValidationError`, `UnauthorizedError`, `UnprocessableEntityError`, and `ServiceUnavailableError` in `src/features/auth/session.ts` cover the other refusal statuses.

## 4. Expose the server functions

Create `src/features/<feature>/server-fns.ts`. Routes import this module, so it must not statically import `#/db`, `#/db/schema`, or `"bun"`. Every `createServerFn` declares `.middleware([...])`; `template/server-fn-requires-session` fails the lint when one does not.

```ts
import { createServerFn } from "@tanstack/react-start";
import { requireSession } from "#/features/auth/session";
import { parseCreateNote } from "#/features/notes/schema";

async function loadServer() {
  return Promise.all([import("#/db"), import("#/features/notes/records.server")]);
}

export const createNote = createServerFn({ method: "POST" })
  .middleware([requireSession])
  .validator(parseCreateNote)
  .handler(async ({ data, context }) => {
    const [{ db }, { handleCreateNote }] = await loadServer();
    return handleCreateNote(data, context.user, db);
  });
```

The middleware pipeline checks the session before the handler runs, so the handler receives a non-null `context.user`. See [Server Functions & Bundle Isolation](./DEVELOPMENT.md#server-functions--bundle-isolation) for the client-bundle rules.

## 5. Wire the route and the view

A route module declares `Route` and nothing else; the view is a component under `src/features/<feature>/components/`. `template/route-declaration-only` and `template/route-view-source` enforce both. `src/routes/_authenticated/dashboard.tsx` is the reference pair: the route loads the notes, and `src/features/dashboard/components/page.tsx` renders them.

```tsx
// src/routes/_authenticated/dashboard.tsx
import { createFileRoute } from "@tanstack/react-router";
import { DashboardPage } from "#/features/dashboard/components/page";
import { listNotes } from "#/features/notes/server-fns";

export const Route = createFileRoute("/_authenticated/dashboard")({
  loader: async () => {
    const notes = await listNotes();
    return { notes };
  },
  component: DashboardPage,
});
```

The view reads the loader data through `getRouteApi`:

```tsx
// src/features/dashboard/components/page.tsx
import { getRouteApi } from "@tanstack/react-router";

const routeApi = getRouteApi("/_authenticated/dashboard");

export function DashboardPage() {
  const { notes } = routeApi.useLoaderData();
  // render notes
}
```

TanStack Router discovers the file and regenerates `src/routeTree.gen.ts`; do not edit that file by hand. After a mutation succeeds, call `router.invalidate()` so the loader refetches, as the dashboard does.

## 6. Test the feature

- **Unit**: cover the input schema. See `tests/unit/notes-schema.test.ts`.
- **Integration**: call the `handle*` handlers against a Testcontainers Postgres. See `tests/integration/notes.test.ts`.
- **E2E**: add a Playwright smoke test for the route and its guard.

```bash
bun run test:unit
bun run test:integration
bun run test:e2e
```

Before opening a pull request, run the full verification suite in [CONTRIBUTING.md](./CONTRIBUTING.md#pre-pr-verification). A `.server.ts` import that slips into a client-reachable module under the shared directories fails both `template/bundle-no-server-imports` and `bun run build`; run the build as well.
