import { createHash } from "node:crypto";
import { and, desc, eq, inArray, isNull, sql } from "drizzle-orm";
import type { db as Db } from "#/db";
import {
  assessmentSessions,
  participationDrafts,
  professorApprovals,
  rosterRecipients,
  feedbackDeliveries,
  feedbackDeliveryAttempts,
  evidenceRuns,
  participationRuns,
} from "#/db/schema";
import { UnprocessableEntityError } from "#/features/auth/session";
import { handleGetSession } from "#/features/assessments/records.server";
import type { RetrievalScope } from "#/features/evidence/retrieval.server";
import type { AssessmentInputs } from "#/features/assessments/schema";
import type { DraftContent, ModelAudit, Proposal } from "./schema";
import { auditDraft, composeDraft, validateProposal } from "./validation";

type Database = typeof Db;
export const jsonValue = (value: unknown) => sql`cast(${JSON.stringify(value)} as text)::jsonb`;
export async function evidenceFor(sessionId: string, database: Database) {
  const runs = await database
    .select()
    .from(evidenceRuns)
    .where(eq(evidenceRuns.sessionId, sessionId));
  return runs.flatMap(r =>
    r.progress.bundle && ["completed", "needs_review"].includes(r.status)
      ? [{ id: r.id, bundle: r.progress.bundle }]
      : []
  );
}
const canonical = (value: unknown): unknown => {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value)
        .toSorted(([a], [b]) => a.localeCompare(b))
        .map(([k, v]) => [k, canonical(v)])
    );
  return value;
};

export function approvalDigest(
  content: DraftContent,
  recipients: Array<{ studentId: string; email: string; revision: number }>
) {
  return createHash("sha256")
    .update(
      JSON.stringify(
        canonical([
          content,
          recipients
            .map(r => [r.studentId, r.email, r.revision])
            .toSorted(([a], [b]) => String(a).localeCompare(String(b))),
        ])
      )
    )
    .digest("hex");
}
export function developmentRecipient(email: string) {
  if (!/^[a-z0-9][a-z0-9._+-]{0,100}@example\.invalid$/i.test(email))
    throw new UnprocessableEntityError(
      "Development delivery permits only example.invalid test recipients"
    );
  return email.toLowerCase();
}
async function lockSession(tx: Pick<Database, "select">, sessionId: string) {
  await tx
    .select({ id: assessmentSessions.id })
    .from(assessmentSessions)
    .where(eq(assessmentSessions.id, sessionId))
    .for("update");
}
async function refuseSending(tx: Pick<Database, "select">, sessionId: string) {
  const sending = await tx
    .select({ id: feedbackDeliveries.id })
    .from(feedbackDeliveries)
    .innerJoin(participationDrafts, eq(participationDrafts.id, feedbackDeliveries.draftId))
    .where(
      and(eq(participationDrafts.sessionId, sessionId), eq(feedbackDeliveries.state, "sending"))
    )
    .limit(1);
  if (sending.length)
    throw new UnprocessableEntityError(
      "Wait for in-progress delivery to resolve before editing or approving"
    );
}
async function invalidate(tx: Pick<Database, "update" | "select">, sessionId: string) {
  const drafts = await tx
    .select({ id: participationDrafts.id })
    .from(participationDrafts)
    .where(eq(participationDrafts.sessionId, sessionId));
  if (drafts.length)
    await tx
      .update(professorApprovals)
      .set({ invalidatedAt: new Date() })
      .where(
        and(
          inArray(
            professorApprovals.draftId,
            drafts.map(d => d.id)
          ),
          isNull(professorApprovals.invalidatedAt)
        )
      );
}

export async function appendDraft(
  scope: RetrievalScope,
  proposal: Proposal,
  origin: "model" | "professor",
  note: string,
  database: Database,
  expectedVersion?: number,
  modelAudit?: ModelAudit
) {
  const session = await handleGetSession(
    scope.sessionId,
    scope.user,
    database,
    scope.allowFixtures
  );
  validateProposal(
    proposal,
    session.inputs,
    await evidenceFor(scope.sessionId, database),
    session.id
  );
  return database.transaction(async tx => {
    await lockSession(tx, session.id);
    await refuseSending(tx, session.id);
    const rows = await tx
      .select()
      .from(participationDrafts)
      .where(eq(participationDrafts.sessionId, session.id))
      .orderBy(desc(participationDrafts.version))
      .limit(1);
    const previous = rows.at(0);
    if (expectedVersion !== undefined && (previous?.version ?? 0) !== expectedVersion)
      throw new UnprocessableEntityError("Draft changed; reload before editing");
    await invalidate(tx, session.id);
    const content = composeDraft(proposal, session.inputs, note, previous?.content, modelAudit);
    const [draft] = await tx
      .insert(participationDrafts)
      .values({
        sessionId: session.id,
        version: (previous?.version ?? 0) + 1,
        parentId: previous?.id,
        origin,
        content: jsonValue(content),
      })
      .returning();
    return draft;
  });
}
export function unassessedProposal(inputs: AssessmentInputs): Proposal {
  return {
    findings: inputs.roster.flatMap(s =>
      inputs.rubric.criteria.map(c => ({
        studentId: s.id,
        criterionId: c.id,
        status: "insufficient_evidence" as const,
        score: null,
        turnIds: [],
        citations: [],
        justification: "Not yet assessed by the professor",
        limitations: ["Evidence review required"],
      }))
    ),
    feedback: [],
  };
}
export async function createProfessorDraft(scope: RetrievalScope, database: Database) {
  const session = await handleGetSession(
    scope.sessionId,
    scope.user,
    database,
    scope.allowFixtures
  );
  const existing = await database
    .select()
    .from(participationDrafts)
    .where(eq(participationDrafts.sessionId, session.id))
    .limit(1);
  if (existing.length)
    throw new UnprocessableEntityError("A draft already exists; open the latest version");
  return appendDraft(
    scope,
    unassessedProposal(session.inputs),
    "professor",
    "Professor-created unassessed template, not a model assessment",
    database,
    0
  );
}
export async function setRecipient(
  scope: RetrievalScope,
  studentId: string,
  email: string,
  database: Database
) {
  const session = await handleGetSession(
    scope.sessionId,
    scope.user,
    database,
    scope.allowFixtures
  );
  if (!session.inputs.roster.some(s => s.id === studentId))
    throw new UnprocessableEntityError("Unknown roster student");
  const recipient = developmentRecipient(email);
  await database.transaction(async tx => {
    await lockSession(tx, session.id);
    await refuseSending(tx, session.id);
    await tx
      .insert(rosterRecipients)
      .values({ sessionId: session.id, studentId, email: recipient, revision: 1 })
      .onConflictDoUpdate({
        target: [rosterRecipients.sessionId, rosterRecipients.studentId],
        set: { email: recipient, revision: sql`${rosterRecipients.revision} + 1` },
      });
    await invalidate(tx, session.id);
  });
  return { success: true };
}
export async function approveDraft(
  scope: RetrievalScope,
  draftId: string,
  acknowledge: boolean,
  reason: string,
  database: Database
) {
  const session = await handleGetSession(
    scope.sessionId,
    scope.user,
    database,
    scope.allowFixtures
  );
  return database.transaction(async tx => {
    await lockSession(tx, session.id);
    await refuseSending(tx, session.id);
    const rows = await tx
      .select()
      .from(participationDrafts)
      .where(eq(participationDrafts.sessionId, session.id))
      .orderBy(desc(participationDrafts.version))
      .limit(1);
    const draft = rows.at(0);
    if (!draft || draft.id !== draftId)
      throw new UnprocessableEntityError("Only the latest exact draft version can be approved");
    const issues = [
      ...auditDraft(draft.content, session.inputs),
      ...draft.content.audit.issues,
    ].filter(i => i.disposition === "open");
    if (issues.some(i => i.severity === "blocking"))
      throw new UnprocessableEntityError(
        "Complete every roster student's findings and feedback before approval"
      );
    if (issues.length && (!acknowledge || reason.trim().length < 10))
      throw new UnprocessableEntityError(
        "Explicit acknowledgement and a reason are required for unresolved issues"
      );
    const recipients = await tx
      .select()
      .from(rosterRecipients)
      .where(eq(rosterRecipients.sessionId, session.id));
    if (session.inputs.roster.some(s => !recipients.some(r => r.studentId === s.id)))
      throw new UnprocessableEntityError(
        "Set a test recipient for every roster student before approval"
      );
    recipients.forEach(r => developmentRecipient(r.email));
    const digest = approvalDigest(draft.content, recipients);
    const previous = await tx
      .select()
      .from(professorApprovals)
      .where(
        and(eq(professorApprovals.draftId, draft.id), isNull(professorApprovals.invalidatedAt))
      )
      .limit(1);
    const current = previous.at(0);
    if (current?.digest === digest) return { id: current.id };
    await invalidate(tx, session.id);
    const [approval] = await tx
      .insert(professorApprovals)
      .values({
        draftId: draft.id,
        professorId: scope.user.id,
        digest,
        acknowledgement: reason,
        issueIds: jsonValue([...new Set(issues.map(i => i.id))]),
      })
      .returning({ id: professorApprovals.id });
    return approval;
  });
}

export async function reviewState(scope: RetrievalScope, database: Database) {
  await handleGetSession(scope.sessionId, scope.user, database, scope.allowFixtures);
  const drafts = await database
    .select()
    .from(participationDrafts)
    .where(eq(participationDrafts.sessionId, scope.sessionId))
    .orderBy(desc(participationDrafts.version))
    .limit(20);
  const ids = drafts.map(d => d.id);
  // SMTP attempts have finite timeouts. A lost request is ambiguous, never blindly retried.
  if (ids.length) {
    const stale = await database
      .update(feedbackDeliveries)
      .set({ state: "ambiguous", updatedAt: new Date() })
      .where(
        and(
          inArray(feedbackDeliveries.draftId, ids),
          eq(feedbackDeliveries.state, "sending"),
          sql`${feedbackDeliveries.updatedAt} < now() - interval '30 seconds'`
        )
      )
      .returning({ id: feedbackDeliveries.id });
    if (stale.length)
      await database
        .update(feedbackDeliveryAttempts)
        .set({
          state: "ambiguous",
          reason: "Request interrupted; acceptance unknown; automatic retry prohibited",
        })
        .where(
          and(
            inArray(
              feedbackDeliveryAttempts.deliveryId,
              stale.map(d => d.id)
            ),
            eq(feedbackDeliveryAttempts.state, "sending")
          )
        );
  }
  await database
    .update(participationRuns)
    .set({ status: "failed", stopReason: "interrupted_or_deadline" })
    .where(
      and(
        eq(participationRuns.sessionId, scope.sessionId),
        eq(participationRuns.status, "running"),
        sql`${participationRuns.deadlineAt} <= now()`
      )
    );
  return {
    evidence: await evidenceFor(scope.sessionId, database),
    drafts,
    recipients: await database
      .select()
      .from(rosterRecipients)
      .where(eq(rosterRecipients.sessionId, scope.sessionId)),
    approvals: ids.length
      ? await database
          .select()
          .from(professorApprovals)
          .where(inArray(professorApprovals.draftId, ids))
      : [],
    deliveries: ids.length
      ? await database
          .select()
          .from(feedbackDeliveries)
          .where(inArray(feedbackDeliveries.draftId, ids))
      : [],
    attempts: ids.length
      ? await database
          .select({
            id: feedbackDeliveryAttempts.id,
            deliveryId: feedbackDeliveryAttempts.deliveryId,
            attempt: feedbackDeliveryAttempts.attempt,
            state: feedbackDeliveryAttempts.state,
            reason: feedbackDeliveryAttempts.reason,
            messageId: feedbackDeliveryAttempts.messageId,
            startedAt: feedbackDeliveryAttempts.startedAt,
          })
          .from(feedbackDeliveryAttempts)
          .innerJoin(
            feedbackDeliveries,
            eq(feedbackDeliveries.id, feedbackDeliveryAttempts.deliveryId)
          )
          .where(inArray(feedbackDeliveries.draftId, ids))
      : [],
    runs: await database
      .select()
      .from(participationRuns)
      .where(eq(participationRuns.sessionId, scope.sessionId))
      .orderBy(desc(participationRuns.createdAt))
      .limit(10),
  };
}
