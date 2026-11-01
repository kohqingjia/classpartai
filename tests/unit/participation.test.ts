import { describe, expect, it } from "vitest";
import fixture from "../fixtures/assessment-fictional.json";
import { parseImport } from "#/features/assessments/schema";
import {
  unassessedProposal,
  approvalDigest,
  developmentRecipient,
} from "#/features/participation/records.server";
import {
  auditDraft,
  composeDraft,
  totals,
  validateProposal,
} from "#/features/participation/validation";
import { SharedBudget, WORKFLOW_LIMITS } from "#/features/models/budget";
import type { WorkflowProgress } from "#/features/participation/schema";

const inputs = parseImport({ json: JSON.stringify(fixture) }).inputs;
const sessionId = "00000000-0000-4000-8000-000000000001";
describe("provisional judgement and review invariants", () => {
  it("keeps unknown criteria out of totals instead of treating them as zero", () => {
    const proposal = unassessedProposal(inputs);
    validateProposal(proposal, inputs, [], sessionId);
    expect(totals(proposal, inputs, "student-c").total).toBeNull();
    expect(totals(proposal, inputs, "student-c").assessedCriteria).toBe(0);
    expect(auditDraft(proposal, inputs).some(i => i.id === "no-observation:student-c")).toBe(true);
  });
  it("rejects out-of-range scores, unknown students and wrongly attributed turns", () => {
    const proposal = unassessedProposal(inputs);
    const finding = proposal.findings[0];
    Object.assign(finding, { status: "scored", score: 4, turnIds: ["turn-002"] });
    expect(() => validateProposal(proposal, inputs, [], sessionId)).toThrow("Score outside");
    finding.score = 2;
    finding.turnIds = ["turn-004"];
    expect(() => validateProposal(proposal, inputs, [], sessionId)).toThrow("another student");
    finding.studentId = "missing";
    expect(() => validateProposal(proposal, inputs, [], sessionId)).toThrow("Unknown roster");
  });
  it("does not score silent students qualitatively, but respects an explicit observable rule", () => {
    const proposal = unassessedProposal(inputs);
    const finding = proposal.findings.find(f => f.studentId === "student-c");
    if (!finding) throw new Error("Missing fictional finding");
    Object.assign(finding, { status: "scored", score: 0 });
    expect(() => validateProposal(proposal, inputs, [], sessionId)).toThrow("qualitative score");
    const explicit = structuredClone(inputs);
    Object.assign(explicit.rubric.criteria[0], {
      kind: "observable-participation",
      noContributionScore: 0,
    });
    validateProposal(proposal, explicit, [], sessionId);
    finding.score = 1;
    expect(() => validateProposal(proposal, explicit, [], sessionId)).toThrow("qualitative score");
  });
  it("rejects fabricated course citations and peer information in personal feedback", () => {
    const proposal = unassessedProposal(inputs);
    proposal.findings[0].citations = [{ evidenceRunId: sessionId, passageId: sessionId }];
    expect(() => validateProposal(proposal, inputs, [], sessionId)).toThrow("Citation must belong");
    proposal.findings[0].citations = [];
    proposal.feedback = [
      {
        studentId: "student-a",
        strengths: "Fictional Student B scored higher",
        nextStep: "Review your own reasoning",
        limitations: [],
        turnIds: [],
        citations: [],
        goalIds: [],
      },
    ];
    expect(() => validateProposal(proposal, inputs, [], sessionId)).toThrow("another roster");
  });
  it("keeps uncertain attribution explicit and does not use it as scored evidence", () => {
    const uncertain = structuredClone(inputs);
    uncertain.transcript.turns.push({
      id: "uncertain-1",
      startMs: 27000,
      endMs: 30000,
      speaker: {
        kind: "uncertain",
        label: "Unknown student",
        candidateStudentIds: ["student-a"],
        reason: "Reviewer could not establish speaker",
      },
      text: "Fictional uncertain turn",
    });
    const proposal = unassessedProposal(uncertain);
    Object.assign(proposal.findings[0], { status: "scored", score: 2, turnIds: ["uncertain-1"] });
    expect(() => validateProposal(proposal, uncertain, [], sessionId)).toThrow(
      "Uncertain or professor"
    );
    expect(
      auditDraft(unassessedProposal(uncertain), uncertain).some(
        i => i.id === "attribution:uncertain"
      )
    ).toBe(true);
  });
  it("binds approval fingerprints to exact content and recipient revisions", () => {
    const draft = composeDraft(unassessedProposal(inputs), inputs, "Professor draft");
    const recipients = [{ studentId: "student-a", email: "a@example.invalid", revision: 1 }];
    expect(approvalDigest(draft, recipients)).not.toBe(
      approvalDigest(draft, [{ ...recipients[0], revision: 2 }])
    );
    expect(() => developmentRecipient("actual@student.edu")).toThrow("example.invalid");
  });
  it("shares model/tool budgets across roles rather than resetting nested usage", async () => {
    const progress: WorkflowProgress = {
      modelCalls: 0,
      toolCalls: 0,
      tokens: 0,
      usageKind: "reported",
      actions: [],
      latestDraftId: null,
      evidenceRunIds: [],
    };
    const budget = new SharedBudget(progress, new AbortController().signal, async () => undefined);
    budget.tool(WORKFLOW_LIMITS.toolCalls);
    expect(() => budget.tool()).toThrow("Shared workflow budget");
    progress.modelCalls = WORKFLOW_LIMITS.modelCalls;
    await expect(
      budget.call(
        { estimateTokens: () => 1, next: async () => ({ calls: [], tokens: 1 }) },
        [],
        budget.signal
      )
    ).rejects.toThrow("Shared workflow budget");
  });
});

describe("audit dispositions and completeness", () => {
  it("retains a model support issue through revisions until a subsequent audit explains its resolution", () => {
    const proposal = unassessedProposal(inputs);
    const audit = {
      issues: [
        {
          id: "support",
          studentId: "student-a",
          criterionId: "reasoning",
          detail: "Claim needs support",
          kind: "support" as const,
        },
      ],
      resolvedIssueIds: [],
      resolutionReason: "Not resolved",
      notes: "Needs contextual inspection",
    };
    const first = composeDraft(proposal, inputs, "First audit", undefined, audit);
    const revised = composeDraft(proposal, inputs, "Revised interpretation", first);
    expect(revised.audit.modelReviewed).toBe(false);
    expect(revised.audit.issues.find(i => i.id === "model:support")?.disposition).toBe("open");
    const final = composeDraft(proposal, inputs, "Re-audit", revised, {
      ...audit,
      issues: [],
      resolvedIssueIds: ["model:support"],
      resolutionReason: "Unsupported inference removed after inspecting context",
    });
    expect(final.audit.issues.find(i => i.id === "model:support")?.disposition).toBe("revised");
    expect(proposal.findings.every(f => f.score === null)).toBe(true);
    expect(() =>
      composeDraft(proposal, inputs, "Bad resolution", first, {
        ...audit,
        issues: [],
        resolvedIssueIds: ["invented"],
      })
    ).toThrow("existing open");
    expect(() =>
      composeDraft(proposal, inputs, "Bad student", first, {
        ...audit,
        issues: [{ ...audit.issues[0], studentId: "invented" }],
      })
    ).toThrow("unknown student");
  });
});
