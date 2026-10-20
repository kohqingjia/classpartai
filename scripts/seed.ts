// oxlint-disable node/no-process-env, no-console
import { eq } from "drizzle-orm";
import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

import * as schema from "#/db/schema";

export type SeedUser = typeof schema.user.$inferInsert;
export type SeedNote = typeof schema.notes.$inferInsert;

export const seedUsers: SeedUser[] = [
  {
    id: "test-user-1",
    name: "John Doe",
    email: "john.doe@example.com",
    emailVerified: true,
  },
  {
    id: "test-user-2",
    name: "Jane Doe",
    email: "jane.doe@example.com",
    emailVerified: true,
  },
  {
    id: "user-demo-1",
    name: "Demo User",
    email: "demo@example.com",
    emailVerified: true,
  },
];

export const seedNotes: SeedNote[] = [
  {
    title: "Welcome to TanStack Start Template",
    userId: "user-demo-1",
  },
  {
    title: "Inspect server functions in src/features/notes",
    userId: "user-demo-1",
  },
];

export type Database = ReturnType<typeof drizzle<typeof schema>>;

/**
 * Executes idempotent insertion of seed users and default notes. Every caller — the seed CLI,
 * the integration global setup, the E2E global setup — runs against its own database, so the
 * lookup-then-insert below has no concurrent writer to race.
 */
export async function runSeed(database: Database): Promise<void> {
  await database.insert(schema.user).values(seedUsers).onConflictDoNothing();

  const existingDemoNotes = await database
    .select()
    .from(schema.notes)
    .where(eq(schema.notes.userId, "user-demo-1"));

  if (existingDemoNotes.length === 0) {
    await database.insert(schema.notes).values(seedNotes);
  }
}

/**
 * Seeds the database using an existing Drizzle instance, a custom connection string,
 * or the default DATABASE_URL environment variable.
 */
export async function seed(databaseOrUrl?: Database | string): Promise<void> {
  if (databaseOrUrl && typeof databaseOrUrl !== "string") {
    await runSeed(databaseOrUrl);
    return;
  }

  const connectionString = databaseOrUrl ?? process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error("DATABASE_URL environment variable is required for seeding");
  }

  const pool = new Pool({ connectionString });
  const database = drizzle(pool, { schema });

  try {
    await runSeed(database);
  } finally {
    await pool.end();
  }
}

if (import.meta.main) {
  seed()
    .then(() => {
      console.info("Database seeded successfully.");
      process.exit(0);
    })
    .catch((err: unknown) => {
      console.error("Database seed failed:", err);
      process.exit(1);
    });
}
