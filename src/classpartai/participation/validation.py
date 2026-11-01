"""Deterministic rules every draft must satisfy (ported from participation/validation.ts).

These are authoritative: a model can't override them, and the professor can't either.
"""

import re

from classpartai.assessment import AssessmentInputs
from classpartai.evidence import EvidenceBundle
from classpartai.participation.schema import AuditIssue, DraftContent, ModelAudit, Proposal

EvidenceMap = list[tuple[str, EvidenceBundle]]  # (evidence run id, bundle)


class Unprocessable(Exception):
    """A refused action; the message is safe to show the model and the professor."""


def observed_count(inputs: AssessmentInputs, student_id: str) -> int:
    return sum(
        1
        for t in inputs.transcript.turns
        if t.speaker.kind == "student" and t.speaker.studentId == student_id
    )


def validate_proposal(
    proposal: Proposal, inputs: AssessmentInputs, evidence: EvidenceMap, session_id: str
) -> None:
    roster = {s.id: s for s in inputs.roster}
    criteria = {c.id: c for c in inputs.rubric.criteria}
    turns = {t.id: t for t in inputs.transcript.turns}
    keys: set[str] = set()
    for f in proposal.findings:
        if f.studentId not in roster:
            raise Unprocessable("Unknown roster student")
        criterion = criteria.get(f.criterionId)
        if criterion is None:
            raise Unprocessable("Unknown rubric criterion")
        key = f"{f.studentId}:{f.criterionId}"
        if key in keys:
            raise Unprocessable("Duplicate criterion finding")
        keys.add(key)
        if f.status == "scored":
            if f.score is None or not criterion.minScore <= f.score <= criterion.maxScore:
                raise Unprocessable("Score outside the pinned rubric range")
            if observed_count(inputs, f.studentId) == 0:
                if (
                    criterion.kind != "observable-participation"
                    or criterion.noContributionScore is None
                    or f.score != criterion.noContributionScore
                ):
                    raise Unprocessable(
                        "No observed contribution cannot support a qualitative score"
                    )
            elif not f.turnIds:
                raise Unprocessable("Scored findings require attributable transcript evidence")
            if criterion.requiresCourseEvidence and not f.citations:
                raise Unprocessable("This criterion explicitly requires course evidence")
        elif f.score is not None:
            raise Unprocessable("Insufficient evidence must not be counted as zero")
        for turn_id in f.turnIds:
            turn = turns.get(turn_id)
            if turn is None:
                raise Unprocessable("Unknown transcript turn")
            if turn.speaker.kind == "student" and turn.speaker.studentId != f.studentId:
                raise Unprocessable("Turn attributed to another student")
            if turn.speaker.kind != "student" and f.status == "scored":
                raise Unprocessable(
                    "Uncertain or professor turns cannot establish a student's score"
                )

    goals = {g.id for g in inputs.learningGoals or [] if g.approved}
    seen: set[str] = set()
    for fb in proposal.feedback:
        if fb.studentId not in roster or fb.studentId in seen:
            raise Unprocessable("Feedback must reference a unique roster student")
        seen.add(fb.studentId)
        if any(g not in goals for g in fb.goalIds):
            raise Unprocessable("Feedback may reference only professor-approved learning goals")
        for turn_id in fb.turnIds:
            turn = turns.get(turn_id)
            if (
                turn is None
                or turn.speaker.kind != "student"
                or turn.speaker.studentId != fb.studentId
            ):
                raise Unprocessable("Feedback turn evidence must belong to that student")
        body = " ".join([fb.strengths, fb.nextStep, *fb.limitations]).lower()
        if observed_count(inputs, fb.studentId) == 0 and "no observed contribution" not in body:
            raise Unprocessable(
                "Feedback must explicitly record no observed contribution without inferring "
                "understanding"
            )
        for other in inputs.roster:
            if other.id != fb.studentId and (
                other.displayName.lower() in body or other.id.lower() in body
            ):
                raise Unprocessable(
                    "Individual feedback cannot include another roster student's identity or "
                    "assessment"
                )

    bundles = dict(evidence)
    for item in [*proposal.findings, *proposal.feedback]:
        for c in item.citations:
            bundle = bundles.get(c.evidenceRunId)
            if (
                bundle is None
                or bundle.sessionId != session_id
                or bundle.transcriptVersion != inputs.transcript.version
                or bundle.rubric["id"] != inputs.rubric.id
                or bundle.rubric["version"] != inputs.rubric.version
                or not any(x.passageId == c.passageId for x in bundle.citations)
            ):
                raise Unprocessable("Citation must belong to validated evidence for this snapshot")


def totals(proposal: Proposal, inputs: AssessmentInputs, student_id: str) -> dict:
    findings = [f for f in proposal.findings if f.studentId == student_id]
    assessed = [f for f in findings if f.status == "scored" and f.score is not None]
    known = sum(f.score or 0 for f in assessed)
    complete = len(findings) == len(inputs.rubric.criteria) and len(assessed) == len(findings)
    summed = inputs.rubric.aggregation is not None and inputs.rubric.aggregation.method == "sum"
    return {
        "knownSubtotal": known,
        "assessedCriteria": len(assessed),
        "totalCriteria": len(inputs.rubric.criteria),
        "total": known if complete and summed else None,
        "maximum": sum(c.maxScore for c in inputs.rubric.criteria),
        "limitation": (
            "No aggregation rule configured"
            if inputs.rubric.aggregation is None
            else "Incomplete criteria: unknown scores are not zero"
            if not complete
            else "Provisional sum; professor review required"
        ),
    }


TRAIT_CLAIM = re.compile(
    r"lazy|unmotivated|poor understanding|does not understand|lacks ability", re.IGNORECASE
)


def audit_draft(proposal: Proposal, inputs: AssessmentInputs) -> list[AuditIssue]:
    issues: list[AuditIssue] = []

    def add(id_, student_id, criterion_id, detail, severity="review"):
        issues.append(
            AuditIssue(
                id=id_,
                studentId=student_id,
                criterionId=criterion_id,
                kind=id_.split(":")[0],
                detail=detail,
                severity=severity,
                disposition="open",
                resolution=None,
            )
        )

    for s in inputs.roster:
        for c in inputs.rubric.criteria:
            f = next(
                (x for x in proposal.findings if x.studentId == s.id and x.criterionId == c.id),
                None,
            )
            if f is None:
                add(f"coverage:{s.id}:{c.id}", s.id, c.id, "Missing criterion finding", "blocking")
            elif f.status == "insufficient_evidence":
                add(
                    f"uncertainty:{s.id}:{c.id}",
                    s.id,
                    c.id,
                    "Insufficient evidence remains explicitly unassessed",
                )
        fb = next((x for x in proposal.feedback if x.studentId == s.id), None)
        if fb is None:
            add(
                f"feedback:{s.id}",
                s.id,
                None,
                "Every roster student needs an individual draft",
                "blocking",
            )
        elif TRAIT_CLAIM.search(" ".join([fb.strengths, fb.nextStep, *fb.limitations])):
            add(
                f"unsupported-trait:{s.id}",
                s.id,
                None,
                "Feedback contains a potentially unsupported ability or motivation claim",
            )
        if observed_count(inputs, s.id) == 0:
            add(
                f"no-observation:{s.id}",
                s.id,
                None,
                "No observed contribution is not evidence of poor understanding",
            )
    if any(t.speaker.kind == "uncertain" for t in inputs.transcript.turns):
        add(
            "attribution:uncertain",
            None,
            None,
            "The reviewed transcript retains uncertain attribution; do not silently assign "
            "these turns",
        )
    return issues


def compose_draft(
    proposal: Proposal,
    inputs: AssessmentInputs,
    note: str,
    previous: DraftContent | None = None,
    model_audit: ModelAudit | None = None,
) -> DraftContent:
    issues = audit_draft(proposal, inputs)
    if model_audit:
        ids = [i.id for i in model_audit.issues]
        if len(set(ids)) != len(ids):
            raise Unprocessable("Duplicate model audit issue ID")
        open_model = {
            i.id
            for i in (previous.audit.issues if previous else [])
            if i.id.startswith("model:") and i.disposition == "open"
        }
        if any(r not in open_model for r in model_audit.resolvedIssueIds):
            raise Unprocessable("Auditor can resolve only existing open model issues")
        roster = {s.id for s in inputs.roster}
        criteria = {c.id for c in inputs.rubric.criteria}
        for issue in model_audit.issues:
            if issue.studentId is not None and issue.studentId not in roster:
                raise Unprocessable("Auditor referenced an unknown student")
            if issue.criterionId is not None and issue.criterionId not in criteria:
                raise Unprocessable("Auditor referenced an unknown criterion")
            issues.append(
                AuditIssue(
                    **issue.model_dump(exclude={"id"}),
                    id=f"model:{issue.id}",
                    severity="review",
                    disposition="open",
                    resolution=None,
                )
            )
    for old in previous.audit.issues if previous else []:
        if (
            old.id.startswith("model:")
            and old.disposition == "open"
            and not any(i.id == old.id for i in issues)
        ):
            resolved = model_audit is not None and old.id in model_audit.resolvedIssueIds
            issues.append(
                old.model_copy(
                    update={
                        "disposition": "revised",
                        "resolution": model_audit.resolutionReason,
                    }
                )
                if resolved
                else old
            )
    if model_audit is None:
        issues.append(
            AuditIssue(
                id="model-review:pending",
                studentId=None,
                criterionId=None,
                kind="support",
                detail="Model audit unavailable or stale; professor must review support and "
                "contradictions explicitly",
                severity="review",
                disposition="open",
                resolution=None,
            )
        )
    return DraftContent(
        **proposal.model_dump(),
        revisionNote=note,
        audit={
            "modelReviewed": model_audit is not None,
            "notes": model_audit.notes if model_audit else "Professor review required",
            "issues": [i.model_dump() for i in issues],
        },
    )
