import { and, desc, eq, inArray, lte, sql } from "drizzle-orm";
import type { db as Db } from "#/db";
import { assessmentSessions, evidenceRuns } from "#/db/schema";
import { UnprocessableEntityError } from "#/features/auth/session";
import { sourceDigest } from "#/features/assessments/sources.server";
import { env } from "#/env";
import {
  BUDGET,
  contextFor,
  emptyProgress,
  investigate,
  PROMPT_VERSION,
  INSTRUCTIONS,
} from "./agent.server";
import { TOOL_DEFINITIONS } from "./provider.server";
import { fetchPassage, prepareSources, searchPassages } from "./retrieval.server";
import type { RetrievalScope } from "./retrieval.server";
import { configuredDriver } from "#/features/models/local.server";
import type { Driver } from "./agent.server";
import type { Investigation, Progress } from "./schema";

type Database = typeof Db;
const active = ["queued", "running"] as const;
const json = (value: unknown) => sql`cast(${JSON.stringify(value)} as text)::jsonb`;

export async function listEvidenceRuns(scope: RetrievalScope, database: Database) {
  await prepareSources(scope, database);
  // No worker is implied: abandoned request-bound runs are reconciled when next inspected.
  await database
    .update(evidenceRuns)
    .set({ status: "failed", stopReason: "interrupted_request_or_deadline", updatedAt: new Date() })
    .where(
      and(
        eq(evidenceRuns.sessionId, scope.sessionId),
        inArray(evidenceRuns.status, [...active]),
        lte(evidenceRuns.deadlineAt, new Date())
      )
    );
  return database
    .select()
    .from(evidenceRuns)
    .where(eq(evidenceRuns.sessionId, scope.sessionId))
    .orderBy(desc(evidenceRuns.createdAt))
    .limit(10);
}

export async function startInvestigation(
  scope: RetrievalScope,
  request: Investigation,
  database: Database,
  requestSignal: AbortSignal,
  nested?: { driver: Driver; toolUsage: (count: number) => void }
) {
  const session = await prepareSources(scope, database);
  // Validate selected IDs before inserting a run; truncated context is marked explicitly to the model.
  try {
    contextFor(request, session.inputs);
  } catch {
    throw new UnprocessableEntityError("Select transcript turns and criteria from this session");
  }
  const now = new Date();
  const deadline = new Date(now.getTime() + BUDGET.milliseconds);
  const run = await database.transaction(async tx => {
    await tx
      .select({ id: assessmentSessions.id })
      .from(assessmentSessions)
      .where(eq(assessmentSessions.id, session.id))
      .for("update");
    await tx
      .update(evidenceRuns)
      .set({ status: "failed", stopReason: "interrupted_request_or_deadline", updatedAt: now })
      .where(
        and(
          eq(evidenceRuns.sessionId, session.id),
          inArray(evidenceRuns.status, [...active]),
          lte(evidenceRuns.deadlineAt, now)
        )
      );
    const existing = await tx
      .select({ id: evidenceRuns.id })
      .from(evidenceRuns)
      .where(and(eq(evidenceRuns.sessionId, session.id), inArray(evidenceRuns.status, [...active])))
      .limit(1);
    if (existing.length)
      throw new UnprocessableEntityError("An evidence request is already active for this session");
    const [created] = await tx
      .insert(evidenceRuns)
      .values({
        sessionId: session.id,
        request: json(request),
        manifest: json({
          sessionId: session.id,
          formatVersion: session.inputs.formatVersion,
          transcriptVersion: session.inputs.transcript.version,
          rubric: { id: session.inputs.rubric.id, version: session.inputs.rubric.version },
          sources: session.inputs.documents.map(d => ({
            documentId: d.id,
            version: d.version,
            digest: sourceDigest(d),
          })),
          budgets: BUDGET,
        }),
        model: env.LOCAL_MODEL ?? "configuration-blocked",
        promptVersion: PROMPT_VERSION,
        status: "queued",
        progress: json(emptyProgress()),
        deadlineAt: deadline,
      })
      .returning({ id: evidenceRuns.id });
    return created;
  });
  const guard = and(eq(evidenceRuns.id, run.id), inArray(evidenceRuns.status, [...active]));
  let driver: Driver | null;
  try {
    driver = nested?.driver ?? configuredDriver(INSTRUCTIONS, TOOL_DEFINITIONS);
  } catch {
    driver = null;
  }
  if (!driver) {
    await database
      .update(evidenceRuns)
      .set({ status: "failed", stopReason: "provider_not_configured", updatedAt: new Date() })
      .where(guard);
    return run;
  }
  await database
    .update(evidenceRuns)
    .set({ status: "running", updatedAt: new Date() })
    .where(guard);
  const signal = AbortSignal.any([
    requestSignal,
    AbortSignal.timeout(Math.max(1, deadline.getTime() - Date.now())),
  ]);
  let chargedTools = 0;
  const checkpoint = async (progress: Progress) => {
    nested?.toolUsage(progress.toolCalls - chargedTools);
    chargedTools = progress.toolCalls;
    const rows = await database
      .update(evidenceRuns)
      .set({ progress: json(progress), updatedAt: new Date() })
      .where(and(guard, sql`${evidenceRuns.deadlineAt} > now()`))
      .returning({ id: evidenceRuns.id });
    if (!rows.length) throw new Error("Run expired or was reconciled");
  };
  const outcome = await investigate(
    request,
    session.inputs,
    driver,
    {
      search: args => searchPassages(scope, args, database),
      fetch: args => fetchPassage(scope, args, database),
    },
    checkpoint,
    signal
  );
  // A late request must never resurrect a reconciled or expired run as completed.
  const expired = Date.now() >= deadline.getTime();
  await database
    .update(evidenceRuns)
    .set({
      status: expired ? "needs_review" : outcome.status,
      stopReason: expired ? "interrupted_or_timeout" : outcome.stopReason,
      progress: json(outcome.progress),
      updatedAt: new Date(),
    })
    .where(guard);
  return run;
}
