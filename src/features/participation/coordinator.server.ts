/* oxlint-disable no-await-in-loop -- Each coordinator action consumes the prior tool result; the investigative route is model-selected. */
import { z } from "zod";
import { and, desc, eq, sql } from "drizzle-orm";
import type { db as Db } from "#/db";
import {
  assessmentSessions,
  evidenceRuns,
  participationDrafts,
  participationRuns,
} from "#/db/schema";
import { UnprocessableEntityError } from "#/features/auth/session";
import { handleGetSession } from "#/features/assessments/records.server";
import { INSTRUCTIONS as EVIDENCE_INSTRUCTIONS } from "#/features/evidence/agent.server";
import { TOOL_DEFINITIONS as EVIDENCE_TOOLS } from "#/features/evidence/provider.server";
import { startInvestigation } from "#/features/evidence/runs.server";
import { tool } from "#/features/models/local.server";
import { BudgetExceeded, SharedBudget, WORKFLOW_LIMITS } from "#/features/models/budget";
import { env } from "#/env";
import type { RetrievalScope } from "#/features/evidence/retrieval.server";
import { InvestigationSchema } from "#/features/evidence/schema";
import type { WorkflowProgress } from "./schema";
import { appendDraft, evidenceFor, jsonValue, reviewState } from "./records.server";
import { auditDraft } from "./validation";
import { defaultFactory, feedbackFor, judge, modelAudit, ROLE_POLICY } from "./roles.server";
import type { DriverFactory } from "./roles.server";

type Database = typeof Db;
const Inspect = z
  .object({
    studentId: z.string().min(1).max(80).nullable(),
    turnIds: z.array(z.string().min(1).max(80)).max(12),
  })
  .strict();
const Retrieve = z
  .object({
    question: z.string().min(5).max(1500),
    turnIds: z.array(z.string()).min(1).max(8),
    criterionIds: z.array(z.string()).min(1).max(6),
    reuseRunId: z.uuid().nullable(),
  })
  .strict();
const Revise = z.object({ note: z.string().min(3).max(1000) }).strict();
const Student = z.object({ studentId: z.string().min(1).max(80) }).strict();
const Review = z.object({ summary: z.string().min(5).max(1500) }).strict();
export const COORDINATOR_TOOLS = [
  tool(
    "inspect_transcript_context",
    "Inspect reviewed attribution and neighbouring turns instead of searching course sources unnecessarily",
    Inspect
  ),
  tool(
    "retrieve_evidence",
    "Reuse a relevant existing validated run, or invoke the bounded course evidence agent for a question",
    Retrieve
  ),
  tool(
    "propose_rubric_assessment",
    "Invoke the provisional rubric judge, including revisions after audit findings",
    Revise
  ),
  tool(
    "audit_assessment",
    "Run deterministic and model review of support, contradictions and feedback; never automatically lower scores",
    Revise
  ),
  tool(
    "draft_student_feedback",
    "Ask the feedback role to draft for one roster student or request missing evidence",
    Student
  ),
  tool(
    "request_professor_review",
    "Finish only when all required findings/feedback and an audit are ready; never approve or send",
    Review
  ),
];
const COORDINATOR_POLICY = `${ROLE_POLICY}\nGoal: prepare fair evidence-supported provisional participation findings and useful individual feedback for EVERY roster student, ready for professor review. Choose your next action based on tool results, not a fixed sequence. You may inspect context, reuse evidence, retrieve more, judge, audit, revise, request more evidence before feedback, or finish with unresolved uncertainty for professor review. Audit support and contradictions as well as deterministic validity. No-observation findings are not poor-understanding claims. Tool results must be inspected before choosing another action. There are no approval or delivery tools. Use request_professor_review when required drafts and an audit exist; unresolved issues remain visible. Do not call all tools mechanically.`;

export async function coordinate(
  scope: RetrievalScope,
  database: Database,
  requestSignal: AbortSignal,
  factory: DriverFactory = defaultFactory
) {
  const session = await handleGetSession(
    scope.sessionId,
    scope.user,
    database,
    scope.allowFixtures
  );
  await reviewState(scope, database);
  const progress: WorkflowProgress = {
    modelCalls: 0,
    toolCalls: 0,
    tokens: 0,
    usageKind: "reported",
    actions: [],
    latestDraftId: null,
    evidenceRunIds: [],
  };
  const deadline = new Date(Date.now() + WORKFLOW_LIMITS.milliseconds);
  const created = await database.transaction(async tx => {
    await tx
      .select({ id: assessmentSessions.id })
      .from(assessmentSessions)
      .where(eq(assessmentSessions.id, session.id))
      .for("update");
    const active = await tx
      .select({ id: participationRuns.id })
      .from(participationRuns)
      .where(
        and(eq(participationRuns.sessionId, session.id), eq(participationRuns.status, "running"))
      )
      .limit(1);
    if (active.length)
      throw new UnprocessableEntityError("A participation workflow is already active");
    const [run] = await tx
      .insert(participationRuns)
      .values({
        sessionId: session.id,
        status: "running",
        progress: jsonValue(progress),
        manifest: jsonValue({
          transcriptVersion: session.inputs.transcript.version,
          rubricId: session.inputs.rubric.id,
          rubricVersion: session.inputs.rubric.version,
          model: env.LOCAL_MODEL ?? "configuration-blocked",
          promptVersion: "participation-coordinator-v1",
        }),
        deadlineAt: deadline,
      })
      .returning({ id: participationRuns.id });
    return run;
  });
  let driver;
  try {
    driver = factory(COORDINATOR_POLICY, COORDINATOR_TOOLS);
  } catch {
    driver = null;
  }
  if (!driver) {
    await database
      .update(participationRuns)
      .set({ status: "configuration_blocked", stopReason: "free_local_model_not_configured" })
      .where(eq(participationRuns.id, created.id));
    return created;
  }
  const signal = AbortSignal.any([
    requestSignal,
    AbortSignal.timeout(Math.max(1, deadline.getTime() - Date.now())),
  ]);
  const guard = and(eq(participationRuns.id, created.id), eq(participationRuns.status, "running"));
  const checkpoint = async () => {
    const updated = await database
      .update(participationRuns)
      .set({ progress: jsonValue(progress) })
      .where(and(guard, sql`${participationRuns.deadlineAt} > now()`))
      .returning({ id: participationRuns.id });
    if (!updated.length) throw new BudgetExceeded();
  };
  const budget = new SharedBudget(progress, signal, checkpoint);
  const existing = await evidenceFor(session.id, database);
  const history = [
    {
      role: "user",
      content: JSON.stringify({
        untrustedData: {
          sessionId: session.id,
          roster: session.inputs.roster,
          rubric: session.inputs.rubric,
          transcriptVersion: session.inputs.transcript.version,
          turnIds: session.inputs.transcript.turns.map(t => t.id),
          evidenceRuns: existing.map(e => ({
            id: e.id,
            question: e.bundle.question,
            status: e.bundle.status,
            gaps: e.bundle.gaps,
          })),
        },
      }),
    },
  ] as Array<Record<string, unknown>>;
  let stopReason = "shared_budget_exhausted";
  try {
    while (true) {
      signal.throwIfAborted();
      const response = await budget.call(driver, history, signal);
      budget.tool();
      const call = response.calls.at(0);
      if (!call || response.calls.length !== 1)
        throw new Error("Coordinator must choose one tool action at a time");
      const action = {
        id: `${progress.toolCalls}:${call.callId}`,
        tool: COORDINATOR_TOOLS.some(t => t.name === call.name) ? call.name : "unsupported_tool",
        arguments: "{}",
        summary: "Action requested",
        outcome: "started" as "started" | "ok" | "invalid",
      };
      progress.actions.push(action);
      await checkpoint();
      history.push({
        type: "function_call",
        call_id: call.callId,
        name: call.name,
        arguments: call.arguments,
      });
      let output: unknown;
      try {
        const raw: unknown = JSON.parse(call.arguments);
        const drafts = await database
          .select()
          .from(participationDrafts)
          .where(eq(participationDrafts.sessionId, session.id))
          .orderBy(desc(participationDrafts.version))
          .limit(1);
        const draft = drafts.at(0);
        if (call.name === "inspect_transcript_context") {
          const args = Inspect.parse(raw);
          action.arguments = JSON.stringify(args);
          if (args.studentId !== null && !session.inputs.roster.some(s => s.id === args.studentId))
            throw new Error("Unknown roster student");
          if (args.turnIds.some(id => !session.inputs.transcript.turns.some(t => t.id === id)))
            throw new Error("Unknown transcript turn");
          output = {
            reviewedTurns: session.inputs.transcript.turns
              .filter(
                (t, i, turns) =>
                  args.turnIds.includes(t.id) ||
                  (args.studentId !== null &&
                    t.speaker.kind === "student" &&
                    t.speaker.studentId === args.studentId) ||
                  args.turnIds.includes(turns[Math.max(0, i - 1)].id) ||
                  args.turnIds.includes(turns[Math.min(turns.length - 1, i + 1)].id)
              )
              .slice(0, 20),
            limits: "At most 20 context turns; inspect additional stable IDs if needed",
          };
        } else if (call.name === "retrieve_evidence") {
          const args = Retrieve.parse(raw);
          action.arguments = JSON.stringify(args);
          if (args.reuseRunId) {
            const evidence = (await evidenceFor(session.id, database)).find(
              e => e.id === args.reuseRunId
            );
            if (!evidence) throw new Error("Existing evidence is unavailable for this snapshot");
            output = evidence;
          } else {
            const evidenceDriver = factory(EVIDENCE_INSTRUCTIONS, EVIDENCE_TOOLS);
            if (!evidenceDriver) throw new Error("Local model configuration blocked");
            const parsed = InvestigationSchema.parse({
              sessionId: session.id,
              question: args.question,
              turnIds: args.turnIds,
              criterionIds: args.criterionIds,
            });
            const run = await startInvestigation(scope, parsed, database, signal, {
              driver: budget.wrap(evidenceDriver),
              toolUsage: count => budget.tool(count),
            });
            progress.evidenceRunIds.push(run.id);
            const saved = (
              await database.select().from(evidenceRuns).where(eq(evidenceRuns.id, run.id))
            ).at(0);
            output = { id: run.id, status: saved?.status, bundle: saved?.progress.bundle };
          }
        } else if (call.name === "propose_rubric_assessment") {
          const args = Revise.parse(raw);
          action.arguments = JSON.stringify(args);
          const judged = await judge(
            session.inputs,
            await evidenceFor(session.id, database),
            budget,
            factory
          );
          const next = await appendDraft(
            scope,
            { findings: judged.findings, feedback: draft?.content.feedback ?? [] },
            "model",
            args.note,
            database,
            draft?.version ?? 0
          );
          progress.latestDraftId = next.id;
          output = {
            draftId: next.id,
            findings: next.content.findings,
            auditIssues: next.content.audit.issues,
          };
        } else if (call.name === "audit_assessment") {
          const args = Revise.parse(raw);
          action.arguments = JSON.stringify(args);
          if (!draft) throw new Error("Create a provisional draft before audit");
          const audit = await modelAudit(
            session.inputs,
            draft.content,
            await evidenceFor(session.id, database),
            budget,
            factory
          );
          const next = await appendDraft(
            scope,
            { findings: draft.content.findings, feedback: draft.content.feedback },
            "model",
            args.note,
            database,
            draft.version,
            audit
          );
          progress.latestDraftId = next.id;
          output = { draftId: next.id, audit: next.content.audit };
        } else if (call.name === "draft_student_feedback") {
          const args = Student.parse(raw);
          action.arguments = JSON.stringify(args);
          if (!draft) throw new Error("Create findings before feedback");
          const result = await feedbackFor(
            args.studentId,
            session.inputs,
            draft.content,
            await evidenceFor(session.id, database),
            budget,
            factory
          );
          if (result.status === "needs_evidence") output = result;
          else {
            if (result.feedback.studentId !== args.studentId)
              throw new Error("Feedback role returned a different student");
            const next = await appendDraft(
              scope,
              {
                findings: draft.content.findings,
                feedback: [
                  ...draft.content.feedback.filter(f => f.studentId !== args.studentId),
                  result.feedback,
                ],
              },
              "model",
              "Individual feedback draft",
              database,
              draft.version
            );
            progress.latestDraftId = next.id;
            output = {
              draftId: next.id,
              feedbackStudentId: args.studentId,
              auditIssues: next.content.audit.issues,
            };
          }
        } else if (call.name === "request_professor_review") {
          const args = Review.parse(raw);
          action.arguments = JSON.stringify(args);
          if (!draft) throw new Error("No provisional draft exists");
          if (
            auditDraft(draft.content, session.inputs).some(i => i.severity === "blocking") ||
            !draft.content.audit.modelReviewed
          )
            throw new Error(
              "Complete every roster student's outputs and audit the current draft first"
            );
          action.outcome = "ok";
          action.summary =
            "Complete provisional outputs escalated to professor; no approval or delivery performed";
          stopReason = "ready_for_professor_review";
          await checkpoint();
          break;
        } else throw new Error("Unsupported coordinator action");
        if (JSON.stringify(output).length > WORKFLOW_LIMITS.historyBytes / 2)
          throw new BudgetExceeded();
        action.outcome = "ok";
        action.summary =
          "Action completed; inspect the returned result before choosing the next action";
      } catch (error) {
        if (error instanceof BudgetExceeded || signal.aborted) throw new BudgetExceeded();
        action.outcome = "invalid";
        action.summary =
          "Action refused or role output invalid; revise the request, inspect context or escalate";
        output = {
          error: error instanceof UnprocessableEntityError ? error.message : action.summary,
        };
      }
      await checkpoint();
      history.push({
        type: "function_call_output",
        call_id: call.callId,
        output: JSON.stringify({ untrustedToolResult: output }),
      });
    }
  } catch (error) {
    stopReason =
      error instanceof BudgetExceeded || signal.aborted
        ? "shared_budget_or_interruption"
        : "local_provider_failure";
  }
  await database
    .update(participationRuns)
    .set({
      status: stopReason === "local_provider_failure" ? "failed" : "needs_review",
      stopReason,
      progress: jsonValue(progress),
    })
    .where(guard);
  return created;
}
