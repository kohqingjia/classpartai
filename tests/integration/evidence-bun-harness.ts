// oxlint-disable no-console
// RUNTIME TEST DOUBLE ONLY: real Bun SQL and provider adapter, intercepted OpenAI HTTP responses.
import { eq, sql } from "drizzle-orm";
import { db, client } from "#/db";
import { user } from "#/db/schema";
import { parseImport } from "#/features/assessments/schema";
import { handleImportSession } from "#/features/assessments/records.server";
import { searchPassages } from "#/features/evidence/retrieval.server";
import { listEvidenceRuns, startInvestigation } from "#/features/evidence/runs.server";

const person = {
  id: crypto.randomUUID(),
  email: `fictional-runtime-${crypto.randomUUID()}@example.invalid`,
  name: "Fictional runtime test",
};
const originalFetch = globalThis.fetch;
let stage = "create fictional inputs";
try {
  await db.insert(user).values(person);
  const fixture = await Bun.file("tests/fixtures/assessment-fictional.json").json();
  const created = await handleImportSession(
    parseImport({ json: JSON.stringify(fixture) }),
    person,
    db,
    true
  );
  const scope = { sessionId: created.id, user: person, allowFixtures: true };
  const matches = await searchPassages(
    scope,
    { query: "observation", documentId: null, version: null, limit: 1 },
    db
  );
  const passage = matches[0];
  let calls = 0;
  // The branch sequence below is a deterministic HTTP test double, NOT production agent behaviour.
  globalThis.fetch = Object.assign(async () => {
    calls++;
    const name = calls === 1 ? "get_source_passage" : "finish_evidence";
    const args =
      calls === 1
        ? { passageId: passage.passageId, offset: 0 }
        : {
            status: "sufficient",
            explanation: "Fictional runtime test completion",
            turnIds: ["turn-002"],
            citations: [
              {
                passageId: passage.passageId,
                excerpt: passage.text,
                relevance: "Fictional test source defines observation",
                relationship: "supports",
              },
            ],
            conflicts: [],
            gaps: [],
          };
    return Response.json({
      choices: [
        {
          message: {
            tool_calls: [
              { id: `test-call-${calls}`, function: { name, arguments: JSON.stringify(args) } },
            ],
          },
        },
      ],
      usage: { total_tokens: 100 },
    });
  }, originalFetch);
  stage = "persist completed run through Bun SQL";
  const run = await startInvestigation(
    scope,
    {
      sessionId: created.id,
      question: "What is an observation?",
      turnIds: ["turn-002"],
      criterionIds: ["reasoning"],
    },
    db,
    new AbortController().signal
  );
  const saved = (await listEvidenceRuns(scope, db)).find(r => r.id === run.id);
  const kinds = await db.execute(
    sql`select jsonb_typeof(progress) as kind from evidence_runs where id = ${run.id}`
  );
  console.log(
    JSON.stringify({
      status: saved?.status,
      actions: saved?.progress.actions.length,
      validity: saved?.progress.bundle?.citationValidity,
      jsonbObject: kinds[0]?.kind === "object",
      provider: "explicit-http-test-double",
    })
  );
} catch {
  console.log(JSON.stringify({ error: "Bun runtime diagnostic failed", stage }));
  process.exitCode = 1;
} finally {
  globalThis.fetch = originalFetch;
  await db.delete(user).where(eq(user.id, person.id));
  await client.close();
}
