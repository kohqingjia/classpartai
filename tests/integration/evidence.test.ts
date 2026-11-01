import { spawnSync } from "node:child_process";
// oxlint-disable node/no-process-env
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { drizzle } from "drizzle-orm/node-postgres";
import { Pool } from "pg";
import { eq, sql } from "drizzle-orm";
import * as schema from "#/db/schema";
import fixture from "../fixtures/assessment-fictional.json";
import { parseImport } from "#/features/assessments/schema";
import { handleGetSession, handleImportSession } from "#/features/assessments/records.server";
import { fetchPassage, prepareSources, searchPassages } from "#/features/evidence/retrieval.server";
import { listEvidenceRuns, startInvestigation } from "#/features/evidence/runs.server";
import type { RetrievalScope } from "#/features/evidence/retrieval.server";

// Explicitly disable live provider calls in database tests, regardless of a developer's environment.
vi.mock("#/env", () => ({
  env: {
    OPENAI_API_KEY: undefined,
    LOCAL_MODEL: undefined,
    EVIDENCE_MODEL: "test-provider-disabled",
  },
}));
const owner = { id: "evidence-professor", email: "evidence-professor@example.invalid" };
const outsider = { id: "evidence-outsider", email: "evidence-outsider@example.invalid" };
const request = (sessionId: string) => ({
  sessionId,
  question: "What distinguishes observation from interpretation?",
  turnIds: ["turn-002"],
  criterionIds: ["reasoning"],
});

describe("course retrieval and evidence persistence", () => {
  let pool: Pool;
  let db: ReturnType<typeof drizzle<typeof schema>>;
  let database: never;
  let scope: RetrievalScope;
  let otherScope: RetrievalScope;
  beforeAll(async () => {
    pool = new Pool({ connectionString: process.env.DATABASE_URL });
    db = drizzle(pool, { schema });
    database = db as never;
    await db
      .insert(schema.user)
      .values(
        [owner, outsider].map(u => Object.assign({ name: "Fictional evidence test account" }, u))
      );
    const data = parseImport({ json: JSON.stringify(fixture) });
    const created = await handleImportSession(data, owner, database, true);
    const other = await handleImportSession(data, outsider, database, true);
    scope = { sessionId: created.id, user: owner, allowFixtures: true };
    otherScope = { sessionId: other.id, user: outsider, allowFixtures: true };
  });
  afterAll(async () => {
    await db.delete(schema.user).where(eq(schema.user.id, owner.id));
    await db.delete(schema.user).where(eq(schema.user.id, outsider.id));
    await pool.end();
  });

  it("retrieves relevant lexical matches with exact page/source/version references and empty results", async () => {
    const matches = await searchPassages(
      scope,
      { query: "observation", documentId: null, version: null, limit: 5 },
      database
    );
    expect(matches).toHaveLength(1);
    expect(matches[0].documentId).toBe("fictional-reading-a");
    expect(matches[0].page).toBe(1);
    const fetched = await fetchPassage(
      scope,
      { passageId: matches[0].passageId, offset: 0 },
      database
    );
    expect(fetched.text).toContain("An observation describes an event");
    expect(fetched.text.length).toBeLessThanOrEqual(6000);
    expect(
      await searchPassages(
        scope,
        { query: "unfindablewordxyz", documentId: null, version: null, limit: 5 },
        database
      )
    ).toHaveLength(0);
    expect(
      await searchPassages(
        scope,
        { query: "observation", documentId: "fictional-reading-b", version: "1", limit: 1 },
        database
      )
    ).toHaveLength(0);
  });

  it("enforces session/course ownership in both search and passage-fetch queries", async () => {
    const matches = await searchPassages(
      scope,
      { query: "observation", documentId: null, version: null, limit: 1 },
      database
    );
    await expect(
      fetchPassage(otherScope, { passageId: matches[0].passageId, offset: 0 }, database)
    ).rejects.toThrow("Source passage not found");
    const forged = { ...scope, user: outsider };
    expect(
      await searchPassages(
        forged,
        { query: "observation", documentId: null, version: null, limit: 5 },
        database
      )
    ).toHaveLength(0);
    await expect(prepareSources(forged, database)).rejects.toThrow("Assessment session not found");
    await expect(listEvidenceRuns(forged, database)).rejects.toThrow(
      "Assessment session not found"
    );
    await expect(
      startInvestigation(forged, request(scope.sessionId), database, new AbortController().signal)
    ).rejects.toThrow("Assessment session not found");
  });

  it("reuses source versions across sessions and lazily repairs links without changing immutable inputs", async () => {
    const session = await handleGetSession(scope.sessionId, owner, database, true);
    await handleImportSession(
      parseImport({ courseId: session.courseId, json: JSON.stringify(fixture) }),
      owner,
      database,
      true
    );
    expect(
      await db
        .select()
        .from(schema.courseSourceVersions)
        .where(eq(schema.courseSourceVersions.courseId, session.courseId))
    ).toHaveLength(2);
    await db
      .delete(schema.sessionSources)
      .where(eq(schema.sessionSources.sessionId, scope.sessionId));
    await prepareSources(scope, database);
    expect(
      await db
        .select()
        .from(schema.sessionSources)
        .where(eq(schema.sessionSources.sessionId, scope.sessionId))
    ).toHaveLength(2);
    expect((await handleGetSession(scope.sessionId, owner, database, true)).inputs).toEqual(
      session.inputs
    );
    expect(
      await searchPassages(
        { ...scope, allowFixtures: false },
        { query: "observation", documentId: null, version: null, limit: 1 },
        database
      )
    ).toHaveLength(0);
  });

  it("persists missing-provider failures as runs, with object JSONB and immutable input/source manifests", async () => {
    const created = await startInvestigation(
      scope,
      request(scope.sessionId),
      database,
      new AbortController().signal
    );
    const runs = await listEvidenceRuns(scope, database);
    const run = runs.find(r => r.id === created.id);
    expect(run?.status).toBe("failed");
    expect(run?.stopReason).toBe("provider_not_configured");
    expect(run?.manifest.sources).toHaveLength(2);
    expect(run?.progress.modelCalls).toBe(0);
    const result = await db.execute(
      sql`select jsonb_typeof(progress) as kind from evidence_runs where id = ${created.id}`
    );
    expect(result.rows[0].kind).toBe("object");
  });

  it("reconciles stale requests and refuses concurrent duplicate requests", async () => {
    const previous = (await listEvidenceRuns(scope, database))[0];
    const [active] = await db
      .insert(schema.evidenceRuns)
      .values({
        sessionId: scope.sessionId,
        request: sql`cast(${JSON.stringify(request(scope.sessionId))} as text)::jsonb`,
        manifest: sql`cast(${JSON.stringify(previous.manifest)} as text)::jsonb`,
        progress: sql`cast(${JSON.stringify(previous.progress)} as text)::jsonb`,
        model: "test-disabled",
        promptVersion: "test",
        status: "running",
        deadlineAt: new Date(Date.now() + 60000),
      })
      .returning();
    await expect(
      startInvestigation(scope, request(scope.sessionId), database, new AbortController().signal)
    ).rejects.toThrow("already active");
    await db
      .update(schema.evidenceRuns)
      .set({ deadlineAt: new Date(0) })
      .where(eq(schema.evidenceRuns.id, active.id));
    const reconciled = (await listEvidenceRuns(scope, database)).find(r => r.id === active.id);
    expect(reconciled?.status).toBe("failed");
    expect(reconciled?.stopReason).toBe("interrupted_request_or_deadline");
  });
  it("persists a validated completion using real Bun SQL and an explicitly labelled HTTP double", () => {
    const result = spawnSync("bun", ["tests/integration/evidence-bun-harness.ts"], {
      env: {
        ...process.env,
        OPENAI_API_KEY: "fictional-runtime-credential",
        LOCAL_MODEL: "explicit-test-double",
        EVIDENCE_MODEL: "test-double-model",
      },
      encoding: "utf8",
      timeout: 20000,
    });
    expect(result.status).toBe(0);
    expect(JSON.parse(result.stdout)).toEqual({
      status: "completed",
      actions: 2,
      validity: "authorised_retrieved_exact_excerpt",
      jsonbObject: true,
      provider: "explicit-http-test-double",
    });
  });
});
