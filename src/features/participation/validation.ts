import type { AssessmentInputs } from "#/features/assessments/schema";
import type { EvidenceBundle } from "#/features/evidence/schema";
import type { AuditIssue, DraftContent, ModelAudit, Proposal } from "./schema";
import { UnprocessableEntityError } from "#/features/auth/session";

export type EvidenceMap = Array<{ id: string; bundle: EvidenceBundle }>;
export const observedCount = (inputs: AssessmentInputs, studentId: string) =>
  inputs.transcript.turns.filter(
    t => t.speaker.kind === "student" && t.speaker.studentId === studentId
  ).length;

export function validateProposal(
  proposal: Proposal,
  inputs: AssessmentInputs,
  evidence: EvidenceMap,
  sessionId: string
) {
  const keys = new Set<string>();
  for (const finding of proposal.findings) {
    if (!inputs.roster.some(s => s.id === finding.studentId))
      throw new UnprocessableEntityError("Unknown roster student");
    const criterion = inputs.rubric.criteria.find(c => c.id === finding.criterionId);
    if (!criterion) throw new UnprocessableEntityError("Unknown rubric criterion");
    const key = `${finding.studentId}:${finding.criterionId}`;
    if (keys.has(key)) throw new UnprocessableEntityError("Duplicate criterion finding");
    keys.add(key);
    if (finding.status === "scored") {
      if (
        finding.score === null ||
        finding.score < criterion.minScore ||
        finding.score > criterion.maxScore
      )
        throw new UnprocessableEntityError("Score outside the pinned rubric range");
      if (observedCount(inputs, finding.studentId) === 0) {
        if (
          criterion.kind !== "observable-participation" ||
          criterion.noContributionScore === undefined ||
          finding.score !== criterion.noContributionScore
        )
          throw new UnprocessableEntityError(
            "No observed contribution cannot support a qualitative score"
          );
      } else if (!finding.turnIds.length)
        throw new UnprocessableEntityError(
          "Scored findings require attributable transcript evidence"
        );
      if (criterion.requiresCourseEvidence && !finding.citations.length)
        throw new UnprocessableEntityError("This criterion explicitly requires course evidence");
    } else if (finding.score !== null)
      throw new UnprocessableEntityError("Insufficient evidence must not be counted as zero");
    for (const turnId of finding.turnIds) {
      const turn = inputs.transcript.turns.find(t => t.id === turnId);
      if (!turn) throw new UnprocessableEntityError("Unknown transcript turn");
      if (turn.speaker.kind === "student" && turn.speaker.studentId !== finding.studentId)
        throw new UnprocessableEntityError("Turn attributed to another student");
      if (turn.speaker.kind !== "student" && finding.status === "scored")
        throw new UnprocessableEntityError(
          "Uncertain or professor turns cannot establish a student's score"
        );
    }
  }
  const feedbackIds = new Set<string>();
  for (const feedback of proposal.feedback) {
    if (
      !inputs.roster.some(s => s.id === feedback.studentId) ||
      feedbackIds.has(feedback.studentId)
    )
      throw new UnprocessableEntityError("Feedback must reference a unique roster student");
    feedbackIds.add(feedback.studentId);
    if (feedback.goalIds.some(id => !inputs.learningGoals?.some(g => g.id === id && g.approved)))
      throw new UnprocessableEntityError(
        "Feedback may reference only professor-approved learning goals"
      );
    for (const id of feedback.turnIds) {
      const turn = inputs.transcript.turns.find(t => t.id === id);
      if (!turn || turn.speaker.kind !== "student" || turn.speaker.studentId !== feedback.studentId)
        throw new UnprocessableEntityError("Feedback turn evidence must belong to that student");
    }
    const body = [feedback.strengths, feedback.nextStep, ...feedback.limitations]
      .join(" ")
      .toLowerCase();
    if (
      observedCount(inputs, feedback.studentId) === 0 &&
      !body.includes("no observed contribution")
    )
      throw new UnprocessableEntityError(
        "Feedback must explicitly record no observed contribution without inferring understanding"
      );
    if (
      inputs.roster.some(
        s =>
          s.id !== feedback.studentId &&
          (body.includes(s.displayName.toLowerCase()) || body.includes(s.id.toLowerCase()))
      )
    )
      throw new UnprocessableEntityError(
        "Individual feedback cannot include another roster student's identity or assessment"
      );
  }
  for (const item of [...proposal.findings, ...proposal.feedback]) {
    for (const citation of item.citations) {
      const bundle = evidence.find(e => e.id === citation.evidenceRunId)?.bundle;
      if (
        !bundle ||
        bundle.sessionId !== sessionId ||
        bundle.transcriptVersion !== inputs.transcript.version ||
        bundle.rubric.id !== inputs.rubric.id ||
        bundle.rubric.version !== inputs.rubric.version ||
        !bundle.citations.some(c => c.passageId === citation.passageId)
      )
        throw new UnprocessableEntityError(
          "Citation must belong to validated evidence for this snapshot"
        );
    }
  }
}

export function totals(proposal: Proposal, inputs: AssessmentInputs, studentId: string) {
  const findings = proposal.findings.filter(f => f.studentId === studentId);
  const assessed = findings.filter(f => f.status === "scored" && f.score !== null);
  const knownSubtotal = assessed.reduce((sum, f) => sum + (f.score ?? 0), 0);
  const complete =
    findings.length === inputs.rubric.criteria.length && assessed.length === findings.length;
  return {
    knownSubtotal,
    assessedCriteria: assessed.length,
    totalCriteria: inputs.rubric.criteria.length,
    total: complete && inputs.rubric.aggregation?.method === "sum" ? knownSubtotal : null,
    maximum: inputs.rubric.criteria.reduce((sum, c) => sum + c.maxScore, 0),
    limitation: !inputs.rubric.aggregation
      ? "No aggregation rule configured"
      : !complete
        ? "Incomplete criteria: unknown scores are not zero"
        : "Provisional sum; professor review required",
  };
}

export function auditDraft(proposal: Proposal, inputs: AssessmentInputs): AuditIssue[] {
  const issues: AuditIssue[] = [];
  const add = (
    id: string,
    studentId: string | null,
    criterionId: string | null,
    detail: string,
    severity: AuditIssue["severity"] = "review"
  ) =>
    issues.push({
      id,
      studentId,
      criterionId,
      kind: id.split(":")[0],
      detail,
      severity,
      disposition: "open",
      resolution: null,
    });
  for (const student of inputs.roster) {
    for (const criterion of inputs.rubric.criteria) {
      const finding = proposal.findings.find(
        f => f.studentId === student.id && f.criterionId === criterion.id
      );
      if (!finding)
        add(
          `coverage:${student.id}:${criterion.id}`,
          student.id,
          criterion.id,
          "Missing criterion finding",
          "blocking"
        );
      else if (finding.status === "insufficient_evidence")
        add(
          `uncertainty:${student.id}:${criterion.id}`,
          student.id,
          criterion.id,
          "Insufficient evidence remains explicitly unassessed"
        );
    }
    const feedback = proposal.feedback.find(f => f.studentId === student.id);
    if (!feedback)
      add(
        `feedback:${student.id}`,
        student.id,
        null,
        "Every roster student needs an individual draft",
        "blocking"
      );
    else if (
      /lazy|unmotivated|poor understanding|does not understand|lacks ability/i.test(
        [feedback.strengths, feedback.nextStep, ...feedback.limitations].join(" ")
      )
    )
      add(
        `unsupported-trait:${student.id}`,
        student.id,
        null,
        "Feedback contains a potentially unsupported ability or motivation claim"
      );
    if (observedCount(inputs, student.id) === 0)
      add(
        `no-observation:${student.id}`,
        student.id,
        null,
        "No observed contribution is not evidence of poor understanding"
      );
  }
  if (inputs.transcript.turns.some(t => t.speaker.kind === "uncertain"))
    add(
      "attribution:uncertain",
      null,
      null,
      "The reviewed transcript retains uncertain attribution; do not silently assign these turns"
    );
  return issues;
}

export function composeDraft(
  proposal: Proposal,
  inputs: AssessmentInputs,
  note: string,
  previous?: DraftContent,
  modelAudit?: ModelAudit
): DraftContent {
  const issues = auditDraft(proposal, inputs);
  if (modelAudit) {
    if (new Set(modelAudit.issues.map(i => i.id)).size !== modelAudit.issues.length)
      throw new UnprocessableEntityError("Duplicate model audit issue ID");
    if (
      modelAudit.resolvedIssueIds.some(
        id =>
          !previous?.audit.issues.some(
            i => i.id === id && i.id.startsWith("model:") && i.disposition === "open"
          )
      )
    )
      throw new UnprocessableEntityError("Auditor can resolve only existing open model issues");
    for (const issue of modelAudit.issues) {
      if (issue.studentId !== null && !inputs.roster.some(s => s.id === issue.studentId))
        throw new UnprocessableEntityError("Auditor referenced an unknown student");
      if (
        issue.criterionId !== null &&
        !inputs.rubric.criteria.some(c => c.id === issue.criterionId)
      )
        throw new UnprocessableEntityError("Auditor referenced an unknown criterion");
      issues.push({
        ...issue,
        id: `model:${issue.id}`,
        severity: "review",
        disposition: "open",
        resolution: null,
      });
    }
  }
  for (const old of previous?.audit.issues ?? []) {
    if (
      old.id.startsWith("model:") &&
      old.disposition === "open" &&
      !issues.some(i => i.id === old.id)
    ) {
      const resolved = modelAudit?.resolvedIssueIds.includes(old.id);
      issues.push(
        resolved
          ? {
              ...old,
              disposition: "revised",
              resolution: modelAudit?.resolutionReason ?? "Reviewed revision",
            }
          : old
      );
    }
  }
  if (!modelAudit)
    issues.push({
      id: "model-review:pending",
      studentId: null,
      criterionId: null,
      kind: "support",
      detail:
        "Model audit unavailable or stale; professor must review support and contradictions explicitly",
      severity: "review",
      disposition: "open",
      resolution: null,
    });
  return {
    ...proposal,
    revisionNote: note,
    audit: {
      modelReviewed: Boolean(modelAudit),
      notes: modelAudit?.notes ?? "Professor review required",
      issues,
    },
  };
}
