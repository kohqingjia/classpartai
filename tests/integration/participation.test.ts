// oxlint-disable node/no-process-env
import { beforeAll, afterAll, describe, expect, it, vi } from "vitest";
import { Pool } from "pg";
import { drizzle } from "drizzle-orm/node-postgres";
import { eq } from "drizzle-orm";
import * as schema from "#/db/schema";
import { parseImport } from "#/features/assessments/schema";
import { handleImportSession } from "#/features/assessments/records.server";
import {
  appendDraft,
  approveDraft,
  createProfessorDraft,
  reviewState,
  setRecipient,
} from "#/features/participation/records.server";
import { deliverApproved } from "#/features/participation/delivery.server";
import { coordinate } from "#/features/participation/coordinator.server";
import type { DriverFactory } from "#/features/participation/roles.server";
import type { RetrievalScope } from "#/features/evidence/retrieval.server";
import fixture from "../fixtures/assessment-fictional.json";
import { fictionalProposal } from "../fixtures/participation-proposal";
vi.mock("#/env", () => ({ env: { FEEDBACK_DELIVERY: "mailpit", LOCAL_MODEL: undefined } }));
const owner = { id: "participation-owner", email: "participation-owner@example.invalid" };
const outsider = { id: "participation-outsider", email: "participation-outsider@example.invalid" };
const inputs = parseImport({ json: JSON.stringify(fixture) }).inputs;
const proposal = () => fictionalProposal(inputs);
type CaptureTransport = NonNullable<Parameters<typeof deliverApproved>[3]>;
const failure: DriverFactory = () => ({
  estimateTokens: () => 1,
  next: async () => {
    throw new Error("explicit provider double failure");
  },
});

const signal = () => new AbortController().signal;

describe("participation persistence, orchestration and exact approval delivery", () => {
  let pool: Pool;
  let db: ReturnType<typeof drizzle<typeof schema>>;
  let database: never;
  const fresh = async (): Promise<RetrievalScope> => {
    const session = await handleImportSession(
      parseImport({ json: JSON.stringify(fixture) }),
      owner,
      database,
      true
    );
    return { sessionId: session.id, user: owner, allowFixtures: true };
  };
  const ready = async (scope: RetrievalScope) => {
    const draft = await appendDraft(
      scope,
      proposal(),
      "professor",
      "Fictional professor review",
      database,
      0
    );
    await Promise.all(
      inputs.roster.map(s => setRecipient(scope, s.id, `${s.id}@example.invalid`, database))
    );
    const approval = await approveDraft(
      scope,
      draft.id,
      true,
      "Reviewed uncertainty explicitly for this fictional test",
      database
    );
    return { draft, approval };
  };
  beforeAll(async () => {
    pool = new Pool({ connectionString: process.env.DATABASE_URL });
    db = drizzle(pool, { schema });
    database = db as never;
    await db
      .insert(schema.user)
      .values(
        [owner, outsider].map(u => Object.assign({ name: "Fictional participation tester" }, u))
      );
  });
  afterAll(async () => {
    await db.delete(schema.user).where(eq(schema.user.id, owner.id));
    await db.delete(schema.user).where(eq(schema.user.id, outsider.id));
    await pool.end();
  });
  it("rejects access and real recipients, and blocks incomplete or unacknowledged approval", async () => {
    const scope = await fresh();
    await expect(reviewState({ ...scope, user: outsider }, database)).rejects.toThrow("not found");
    await expect(setRecipient(scope, "student-a", "real@university.edu", database)).rejects.toThrow(
      "example.invalid"
    );
    const draft = await createProfessorDraft(scope, database);
    await expect(
      approveDraft(scope, draft.id, true, "Reviewed fictional evidence", database)
    ).rejects.toThrow("every roster");
    const next = await appendDraft(
      scope,
      proposal(),
      "professor",
      "Complete draft",
      database,
      draft.version
    );
    await expect(approveDraft(scope, next.id, false, "", database)).rejects.toThrow(
      "acknowledgement"
    );
  });
  it("versions edits, rejects stale writes and invalidates approvals on recipient or draft changes", async () => {
    const scope = await fresh();
    const { draft, approval } = await ready(scope);
    await setRecipient(scope, "student-a", "changed@example.invalid", database);
    const transport = vi.fn<CaptureTransport>();
    await expect(deliverApproved(scope, approval.id, database, transport)).rejects.toThrow(
      "Approval"
    );
    expect(transport).not.toHaveBeenCalled();
    const renewed = await approveDraft(
      scope,
      draft.id,
      true,
      "Reviewed changed test recipient",
      database
    );
    const next = await appendDraft(
      scope,
      proposal(),
      "professor",
      "Revise feedback",
      database,
      draft.version
    );
    expect(next.version).toBe(2);
    expect(next.parentId).toBe(draft.id);
    await expect(
      appendDraft(scope, proposal(), "professor", "Stale edit", database, draft.version)
    ).rejects.toThrow("reload");
    await expect(deliverApproved(scope, renewed.id, database, transport)).rejects.toThrow(
      "Approval"
    );
    const state = await reviewState(scope, database);
    expect(state.drafts).toHaveLength(2);
    expect(state.approvals.every(a => a.invalidatedAt !== null)).toBe(true);
  });
  it("claims concurrent sends once per student and refuses edits during SMTP", async () => {
    const scope = await fresh();
    const { approval } = await ready(scope);
    let notify!: () => void;
    let release!: () => void;
    const entered = new Promise<void>(resolve => {
      notify = resolve;
    });
    const hold = new Promise<void>(resolve => {
      release = resolve;
    });
    const transport = vi.fn<CaptureTransport>(async () => {
      notify();
      await hold;
      return { messageId: "fictional-smtp-accepted" };
    });
    const first = deliverApproved(scope, approval.id, database, transport);
    await entered;
    await expect(setRecipient(scope, "student-a", "new@example.invalid", database)).rejects.toThrow(
      "in-progress"
    );
    const second = deliverApproved(scope, approval.id, database, transport);
    release();
    await Promise.all([first, second]);
    await deliverApproved(scope, approval.id, database, transport);
    expect(transport).toHaveBeenCalledTimes(3);
    const state = await reviewState(scope, database);
    expect(state.deliveries).toHaveLength(3);
    expect(state.deliveries.every(d => d.state === "accepted" && d.attempts === 1)).toBe(true);
    expect(state.attempts).toHaveLength(3);
  });
  it("retries definite rejection explicitly but never ambiguous acceptance", async () => {
    const scope = await fresh();
    const { approval } = await ready(scope);
    const rejected = vi.fn<CaptureTransport>(async () => {
      throw Object.assign(new Error("test refused"), { code: "ECONNREFUSED" });
    });
    await deliverApproved(scope, approval.id, database, rejected);
    const accepted = vi.fn<CaptureTransport>(async () => ({ messageId: "fictional-retry" }));
    await deliverApproved(scope, approval.id, database, accepted);
    expect(accepted).toHaveBeenCalledTimes(3);
    expect((await reviewState(scope, database)).deliveries.every(d => d.attempts === 2)).toBe(true);
    const uncertain = await fresh();
    const approved = await ready(uncertain);
    const ambiguous = vi.fn<CaptureTransport>(async () => {
      throw new Error("connection lost after DATA");
    });
    await deliverApproved(uncertain, approved.approval.id, database, ambiguous);
    await deliverApproved(uncertain, approved.approval.id, database, ambiguous);
    expect(ambiguous).toHaveBeenCalledTimes(3);
    expect(
      (await reviewState(uncertain, database)).deliveries.every(d => d.state === "ambiguous")
    ).toBe(true);
  });
  it("records configuration blocking, provider failure, active-request guard and stale interruption", async () => {
    const scope = await fresh();
    await coordinate(scope, database, signal(), () => null);
    let state = await reviewState(scope, database);
    expect(state.runs[0].status).toBe("configuration_blocked");
    await coordinate(scope, database, signal(), failure);
    state = await reviewState(scope, database);
    expect(state.runs[0].status).toBe("failed");
    await db
      .update(schema.participationRuns)
      .set({ status: "running", deadlineAt: new Date(Date.now() + 60000) })
      .where(eq(schema.participationRuns.id, state.runs[0].id));
    await expect(coordinate(scope, database, signal(), () => null)).rejects.toThrow(
      "already active"
    );
    await db
      .update(schema.participationRuns)
      .set({ deadlineAt: new Date(0) })
      .where(eq(schema.participationRuns.id, state.runs[0].id));
    expect((await reviewState(scope, database)).runs[0].stopReason).toBe("interrupted_or_deadline");
    expect(state.drafts).toHaveLength(0);
  });
  it("persists a result-dependent audit/revision handoff and drafts for every student using an explicit provider double", async () => {
    const scope = await fresh();
    let judged = 0;
    let audited = 0;
    let step = 0;
    const coordinatorHistories: string[] = [];
    // This deterministic test double checks the tool protocol and state handoff; it is NOT live model agency.
    const actions = [
      ["inspect_transcript_context", { studentId: "student-a", turnIds: ["turn-002"] }],
      ["propose_rubric_assessment", { note: "Initial fictional judgement" }],
      ["audit_assessment", { note: "Check supporting interpretations" }],
      ["inspect_transcript_context", { studentId: "student-b", turnIds: ["turn-004"] }],
      ["propose_rubric_assessment", { note: "Revision after support audit" }],
      ...inputs.roster.map(s => ["draft_student_feedback", { studentId: s.id }] as const),
      ["audit_assessment", { note: "Review revised findings and every feedback draft" }],
      ["request_professor_review", { summary: "Uncertainty retained for professor review" }],
    ] as const;
    const factory: DriverFactory = (_instructions, tools) => ({
      estimateTokens: () => 1,
      next: async history => {
        let name: string;
        let args: unknown;
        if (tools[0].name === "inspect_transcript_context") {
          const action = actions[step++];
          if (!action) throw new Error("Test route exhausted");
          coordinatorHistories.push(JSON.stringify(history));
          [name, args] = action;
        } else {
          name = tools[0].name;
          if (name === "finish_rubric_judgement") {
            judged++;
            args = { findings: proposal().findings };
          } else if (name === "finish_assessment_audit") {
            audited++;
            args = {
              issues:
                audited === 1
                  ? [
                      {
                        id: "support-gap",
                        studentId: "student-b",
                        criterionId: "reasoning",
                        detail: "Interpretation needs contextual review",
                        kind: "support",
                      },
                    ]
                  : [],
              resolvedIssueIds: audited === 2 ? ["model:support-gap"] : [],
              resolutionReason: "Context inspected and unsupported interpretation left unassessed",
              notes: "Explicit fictional audit result",
            };
          } else {
            const target = JSON.parse(String(history[0].content)).untrustedData.student.id;
            args = {
              status: "draft",
              feedback: proposal().feedback.find(f => f.studentId === target),
            };
          }
        }
        return {
          tokens: 5,
          calls: [{ callId: `double-${step}-${name}`, name, arguments: JSON.stringify(args) }],
        };
      },
    });
    await coordinate(scope, database, signal(), factory);
    const state = await reviewState(scope, database);
    expect(state.runs[0].stopReason).toBe("ready_for_professor_review");
    expect(coordinatorHistories[3]).toContain("Interpretation needs contextual review");
    expect(judged).toBe(2);
    expect(audited).toBe(2);
    expect(state.drafts[0].content.feedback).toHaveLength(3);
    expect(
      state.drafts[0].content.audit.issues.find(i => i.id === "model:support-gap")?.disposition
    ).toBe("revised");
    expect(state.runs[0].progress.modelCalls).toBeGreaterThan(step);
    expect(state.approvals).toHaveLength(0);
    expect(state.deliveries).toHaveLength(0);
  });
});
