// oxlint-disable node/no-process-env
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { Pool } from "pg";
import { drizzle } from "drizzle-orm/node-postgres";
import { eq } from "drizzle-orm";
import * as schema from "#/db/schema";
import { parseImport } from "#/features/assessments/schema";
import {
  handleGetSession,
  handleImportSession,
  handleListSessions,
} from "#/features/assessments/records.server";
import fixture from "../fixtures/assessment-fictional.json";

const professor = { id: "assessment-professor", email: "assessment-professor@example.invalid" };
const outsider = { id: "assessment-outsider", email: "assessment-outsider@example.invalid" };
const payload = () => parseImport({ json: JSON.stringify(fixture) });

describe("assessment course boundaries and immutable inputs", () => {
  let pool: Pool;
  let db: ReturnType<typeof drizzle<typeof schema>>;
  let database: never;
  beforeAll(async () => {
    pool = new Pool({ connectionString: process.env.DATABASE_URL });
    db = drizzle(pool, { schema });
    database = db as never;
    await db
      .insert(schema.user)
      .values(
        [professor, outsider].map(u => Object.assign({ name: "Fictional test professor" }, u))
      );
  });
  afterAll(async () => {
    await db.delete(schema.user).where(eq(schema.user.id, professor.id));
    await db.delete(schema.user).where(eq(schema.user.id, outsider.id));
    await pool.end();
  });

  it("persists all reviewed inputs with roster IDs independent of login accounts", async () => {
    const created = await handleImportSession(payload(), professor, database, true);
    const saved = await handleGetSession(created.id, professor, database, true);
    expect(saved.inputs).toEqual(payload().inputs);
    expect(saved.inputs.roster).toHaveLength(3);
    expect(
      (await handleListSessions(professor, database, true)).some(s => s.id === created.id)
    ).toBe(true);
    expect(await db.select().from(schema.user).where(eq(schema.user.id, "student-a"))).toHaveLength(
      0
    );
  });

  it("hides sessions from other professors and refuses foreign-course imports", async () => {
    const created = await handleImportSession(payload(), professor, database, true);
    const saved = await handleGetSession(created.id, professor, database, true);
    expect(await handleListSessions(outsider, database, true)).toHaveLength(0);
    await expect(handleGetSession(created.id, outsider, database, true)).rejects.toThrow(
      "Assessment session not found"
    );
    await expect(
      handleImportSession({ ...payload(), courseId: saved.courseId }, outsider, database, true)
    ).rejects.toThrow("Course not found");
  });

  it("keeps fixtures out of production import and reads", async () => {
    await expect(handleImportSession(payload(), professor, database, false)).rejects.toThrow(
      "only be imported in development"
    );
    const created = await handleImportSession(payload(), professor, database, true);
    await expect(handleGetSession(created.id, professor, database, false)).rejects.toThrow(
      "Assessment session not found"
    );
    expect(await handleListSessions(professor, database, false)).toHaveLength(0);
  });

  it("appends new session snapshots and rejects changes under an existing rubric version", async () => {
    const created = await handleImportSession(payload(), professor, database, true);
    const original = await handleGetSession(created.id, professor, database, true);
    const value = structuredClone(fixture);
    value.rubric.criteria[0].maxScore = 4;
    const changed = parseImport({ courseId: original.courseId, json: JSON.stringify(value) });
    await expect(handleImportSession(changed, professor, database, true)).rejects.toThrow(
      "requires a new version"
    );
    value.rubric.version = "2";
    const next = await handleImportSession(
      parseImport({ courseId: original.courseId, json: JSON.stringify(value) }),
      professor,
      database,
      true
    );
    expect(next.id).not.toBe(created.id);
    expect(
      (await handleGetSession(created.id, professor, database, true)).inputs.rubric.version
    ).toBe("1");
  });

  it("rejects changed cited passages under the same document version and mixed provenance", async () => {
    const created = await handleImportSession(payload(), professor, database, true);
    const original = await handleGetSession(created.id, professor, database, true);
    const value = structuredClone(fixture);
    value.documents[0].passages[0].text = "Fictional edited passage";
    await expect(
      handleImportSession(
        parseImport({ courseId: original.courseId, json: JSON.stringify(value) }),
        professor,
        database,
        true
      )
    ).rejects.toThrow("document content requires a new version");
    const reviewed = parseImport({
      courseId: original.courseId,
      json: JSON.stringify({ ...fixture, provenance: "reviewed" }),
    });
    await expect(handleImportSession(reviewed, professor, database, true)).rejects.toThrow(
      "separate courses"
    );
  });
});
