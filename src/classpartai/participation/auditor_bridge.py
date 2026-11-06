"""Links Le Yong's Auditor agent (auditor_agent/) to the assessment workflow's audit step.

``agent_audit(...)`` is a drop-in for ``roles.model_audit``: same inputs, same ``ModelAudit``
result, so records, ``compose_draft``, the coordinator and the UI work unchanged.

- **Inputs.** The draft, transcript, rubric and the session's validated evidence bundles are
  mapped into the Auditor's v1 ``AuditRequest``. One contribution per student holds that
  student's own reviewed turns; a finding cites the student's turns it names. Fields the workflow
  does not have are filled honestly: ``transcription_confidence`` is null, ``course_id`` is
  derived from the course title, and findings the contract cannot express (a student with no
  turns, or a finding that cites none of the student's turns) are left out and listed in the
  notes rather than given invented turns.
- **Model and budget.** The Auditor's model is the app's driver from the coordinator's factory
  (OpenAI via ``OPENAI_MODEL``). Every Auditor model call, nested citation reviews included,
  goes through ``SharedBudget.call`` and every returned tool call through ``SharedBudget.tool``,
  so they count against ``WORKFLOW_LIMITS``. The Auditor's own limits are capped by what is left,
  and a call left running by an Auditor timeout is waited for (and counted) before the
  coordinator continues.
- **Output.** Auditor issues become ``ModelAuditIssue``s (one per affected finding) with the
  Auditor's own kind and severity kept in the text. A re-judge request is reported as issues
  plus a note for the coordinator; the Auditor never changes a score. Deterministic
  validation (``validation.py``) still runs on every draft and stays authoritative. A later
  ``audit_passed`` (every audited finding inspected, every citation verified, nothing left)
  resolves the Auditor's own earlier open issues on those findings.
- **Feedback.** The Auditor's contract has no feedback, so ``roles.feedback_audit`` (one
  structured call) reviews the feedback drafts and its issues are merged in.
- **Fallback.** If the Auditor errors (a mapping/contract failure, a provider or reader failure,
  or no model), the workflow falls back to the single-call ``model_audit`` and the notes and the
  role trace say so. ``AUDITOR=model`` uses ``model_audit`` directly.

One re-judge round is tracked per coordinator run in memory (``AuditorSession``): after a
``rejudge_requested`` result, the next audit is submitted as the revision if the finding set is
unchanged, otherwise as a fresh case. Nothing is persisted across runs.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field

from classpartai import config
from classpartai.assessment import AssessmentInputs
from classpartai.auditor_agent import audit_proposal
from classpartai.auditor_agent.agent import PROMPT, SCORE_PROMPT, native_arguments
from classpartai.auditor_agent.contracts import AuditRequest, AuditResult, ContractError, Scope
from classpartai.auditor_agent.harness import (
    TOOLS,
    BudgetExhausted,
    Limits,
    ProviderFailure,
    ToolCall,
    ToolResponseError,
    safe_provider_diagnostic,
)
from classpartai.auditor_agent.tools import Evidence
from classpartai.models import (
    WORKFLOW_LIMITS,
    BudgetExceeded,
    SharedBudget,
    ToolDefinition,
)
from classpartai.participation.roles import (
    ROLE_POLICY,
    DriverFactory,
    feedback_audit,
    model_audit,
)
from classpartai.participation.schema import DraftContent, ModelAudit, ModelAuditIssue
from classpartai.participation.validation import EvidenceMap

ROLE_NAME = "auditor_agent"
MAX_TURNS = 12  # Contribution.turn_ids / Finding.transcript_turn_ids limit in contracts.py
MAX_EVIDENCE = 6  # Finding.evidence limit
# Auditor stop reasons that mean "the agent failed", not "the agent decided".
FAILED = {"provider_or_reader_failure", "configuration_blocked"}
KINDS = {
    "citation": "support",
    "rationale": "support",
    "missing_evidence": "uncertainty",
    "consistency": "contradiction",
    "attribution": "attribution",
    "fairness": "uncertainty",
    "injection": "uncertainty",
    "execution": "uncertainty",
}
ID_CHARS = re.compile(r"[^A-Za-z0-9_.:-]")


@dataclass
class AuditorSession:
    """One coordinator run's Auditor state: case count and any pending one-round re-judge."""

    cases: int = 0
    pending: dict | None = None  # {"case", "state", "finding_ids"} after rejudge_requested
    app_ids: dict[str, str] = field(default_factory=dict)  # Auditor issue/finding -> app id


@dataclass
class Mapping:
    request: dict
    evidence: dict[str, Evidence]
    findings: dict[str, tuple[str, str]]  # finding_id -> (studentId, criterionId)
    evidence_refs: dict[str, str]  # evidence_id -> "evidenceRunId/passageId"
    excluded: list[str]
    limitations: list[str]
    revision: bool


def _digest(*parts: object, n: int = 12) -> str:
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:n]


def _slug(value: str, fallback: str) -> str:
    slug = ID_CHARS.sub("-", value.strip())[:60].strip("-")
    return slug or fallback


def build_request(
    inputs: AssessmentInputs,
    draft_id: str,
    draft: DraftContent,
    evidence: EvidenceMap,
    session_id: str,
    session: AuditorSession,
) -> Mapping:
    """Map the workflow's data into an AuditRequest dict. Raises ContractError if it can't."""
    scope = {"course_id": _slug(inputs.courseTitle, "course"), "session_id": session_id}
    rubric = {
        "rubric_id": inputs.rubric.id,
        "version": inputs.rubric.version,
        "criteria": [
            {
                "criterion_id": c.id,
                "description": (
                    f"{c.title}: {c.description}"
                    + (f" Kind: {c.kind}." if c.kind else "")
                    + (
                        f" No-contribution score: {c.noContributionScore}."
                        if c.noContributionScore is not None
                        else ""
                    )
                    + (" Requires course evidence." if c.requiresCourseEvidence else "")
                )[:2000],
                "minimum": c.minScore,
                "maximum": c.maxScore,
            }
            for c in inputs.rubric.criteria
        ],
    }
    limitations: list[str] = []

    # One contribution per student: their own reviewed turns, grouped into at most 12 segments.
    contributions, segment_of = [], {}
    for s in inputs.roster:
        own = [
            t
            for t in inputs.transcript.turns
            if t.speaker.kind == "student" and t.speaker.studentId == s.id
        ]
        if not own:
            continue
        size = -(-len(own) // MAX_TURNS)  # ceil: turns per segment
        groups = [own[i : i + size] for i in range(0, len(own), size)]
        if size > 1:
            limitations.append(f"{s.id}: {len(own)} turns grouped into {len(groups)} segments")
        turn_ids = []
        for n, group in enumerate(groups, 1):
            seg = group[0].id if size == 1 else f"{s.id}-segment-{n}"
            turn_ids.append(seg)
            for t in group:
                segment_of[t.id] = seg
        body = "\n".join(f"[{t.id}] {t.text}" for t in own)
        if len(body) > 6000:
            body = body[:5980] + "\n[truncated]"
            limitations.append(f"{s.id}: contribution text truncated to 6000 characters")
        contributions.append(
            {
                "contribution_id": f"contribution-{s.id}",
                "turn_ids": turn_ids,
                "student_id": s.id,
                # Only the student's own reviewed turns are included, so attribution is
                # identified; uncertain turns stay with audit_draft's attribution check.
                "attribution": "identified",
                "text": body,
                "start_ms": own[0].startMs,
                "end_ms": max(t.endMs for t in own),
                "transcription_confidence": None,  # the workflow has no ASR confidence
            }
        )
    has_contribution = {c["student_id"] for c in contributions}

    bundles = dict(evidence)
    passages = {(d.id, p.id): p for d in inputs.documents for p in d.passages}
    evidence_ids: dict[tuple[str, str], str] = {}
    readable: dict[str, Evidence] = {}
    refs: dict[str, dict] = {}
    labels: dict[str, str] = {}
    findings, finding_map, excluded = [], {}, []
    criteria_order = {c.id: n for n, c in enumerate(inputs.rubric.criteria)}
    for f in sorted(
        draft.findings, key=lambda f: (f.studentId, criteria_order.get(f.criterionId, 0))
    ):
        key = f"{f.studentId}:{f.criterionId}"
        if f.studentId not in has_contribution:
            excluded.append(f"{key} (no attributable turns)")
            continue
        cited = list(dict.fromkeys(segment_of[t] for t in f.turnIds if t in segment_of))
        if not cited:
            excluded.append(f"{key} (cites none of the student's turns)")
            continue
        finding_id = key if len(key) <= 100 else f"finding-{_digest(key)}"
        finding_map[finding_id] = (f.studentId, f.criterionId)
        ev = []
        for c in f.citations:
            bundle = bundles.get(c.evidenceRunId)
            cite = (
                next((x for x in bundle.citations if x.passageId == c.passageId), None)
                if bundle
                else None
            )
            if cite is None:
                limitations.append(f"{key}: citation {c.passageId} not found in its bundle")
                continue
            ref_key = (c.evidenceRunId, c.passageId)
            if ref_key not in evidence_ids:
                eid = f"evidence-{len(evidence_ids) + 1}"
                evidence_ids[ref_key] = eid
                labels[eid] = f"{c.evidenceRunId}/{c.passageId}"
                refs[eid] = {
                    "evidence_id": eid,
                    "source_id": cite.documentId,
                    "source_version": cite.version,
                    "passage_id": cite.passageKey,
                    "page": cite.page,
                    "quote": cite.excerpt[:4000],
                }
                passage = passages.get((cite.documentId, cite.passageKey))
                if passage is not None:
                    text = passage.text
                    if len(text) > 6000:  # keep a window that still contains the quote
                        at = max(0, text.find(cite.excerpt))
                        text = text[max(0, at - 1000) : max(0, at - 1000) + 6000]
                    readable[eid] = Evidence(
                        Scope(**scope),
                        eid,
                        cite.documentId,
                        cite.version,
                        cite.passageKey,
                        cite.page,
                        text,
                    )
            if len(ev) < MAX_EVIDENCE and refs[evidence_ids[ref_key]] not in ev:
                ev.append(refs[evidence_ids[ref_key]])
        if len(f.citations) > MAX_EVIDENCE:
            limitations.append(f"{key}: only the first {MAX_EVIDENCE} citations audited")
        rationale = f.justification
        if f.limitations:
            rationale += " Limitations: " + "; ".join(f.limitations)
        findings.append(
            {
                "finding_id": finding_id,
                "contribution_id": f"contribution-{f.studentId}",
                "criterion_id": f.criterionId,
                "score": f.score if f.status == "scored" else None,
                "rationale": rationale[:2000],
                "transcript_turn_ids": cited[:MAX_TURNS],
                "evidence": ev,
            }
        )
    if not findings:
        raise ContractError("No finding has attributable turns for the Auditor to audit")

    proposal_id = f"draft-{_slug(session_id, 'session')}"
    pending = session.pending
    revision = pending is not None and pending["finding_ids"] == sorted(finding_map)
    if revision:
        state = pending["state"]
        case_id = pending["case"]
        previous = state["last_proposal"]
        proposal_ref = {"proposal_id": previous["proposal_id"], "version": previous["version"] + 1}
        lineage = (previous, state["pending_rejudge"]["request_id"])
    else:
        if pending is not None:
            limitations.append(
                "Earlier re-judge request not linked: the finding set changed; audited afresh"
            )
        case_id = f"audit-{_digest(session_id, draft_id, session.cases)}"
        state = {
            "schema_version": 1,
            "audit_case_id": case_id,
            "scope": scope,
            "rubric_id": inputs.rubric.id,
            "rubric_version": inputs.rubric.version,
            "state_version": 0,
            "rejudge_count": 0,
            "last_proposal": None,
            "pending_rejudge": None,
            "terminal": False,
            "input_fingerprint": None,
            "finding_bindings": {},
        }
        proposal_ref = {"proposal_id": proposal_id, "version": 1}
        lineage = (None, None)
    request = {
        "schema_version": 1,
        "audit_case_id": case_id,
        "trusted_scope": scope,
        "rubric": rubric,
        "contributions": contributions,
        "proposal": {
            "schema_version": 1,
            "reference": proposal_ref,
            "previous_proposal": lineage[0],
            "rejudge_request_id": lineage[1],
            "rubric_id": inputs.rubric.id,
            "rubric_version": inputs.rubric.version,
            "findings": findings,
        },
        "state": state,
    }
    try:  # fail here, before any model call, if the mapping is invalid
        AuditRequest.parse(request)
    except ContractError:
        if not revision:
            raise
        # The revision broke the one-round lineage (e.g. changed reviewed inputs): start afresh.
        session.pending = None
        fresh = build_request(inputs, draft_id, draft, evidence, session_id, session)
        fresh.limitations.append("Earlier re-judge request not linked: lineage check failed")
        return fresh
    return Mapping(request, readable, finding_map, labels, excluded, limitations, revision)


class ScopedReader:
    """Evidence for this session only: built from its validated bundles and documents."""

    def __init__(self, scope: dict, evidence: dict[str, Evidence]):
        self.scope = Scope(**scope)
        self.evidence = evidence

    def read(self, scope: Scope, evidence_id: str, *, timeout: float) -> Evidence | None:
        if scope != self.scope:
            return None
        return self.evidence.get(evidence_id)


class WorkflowModel:
    """The Auditor's ``Model`` protocol on top of the app's driver and shared budget."""

    def __init__(self, budget: SharedBudget, factory: DriverFactory):
        self.budget = budget
        self.factory = factory
        self.drivers: dict[tuple, object] = {}
        self.shared_budget_exhausted = False
        self.closed = False
        self.in_flight = 0
        self.idle = threading.Condition()

    def settle(self, timeout: float) -> bool:
        """Close to new calls and wait for in-flight ones (left running by a harness timeout)
        to finish, so their usage is counted before the coordinator continues."""
        with self.idle:
            self.closed = True
            return self.idle.wait_for(lambda: self.in_flight == 0, max(0.0, timeout))

    def choose(self, messages: list[dict], tools: list[dict], *, timeout: float) -> ToolCall:
        with self.idle:
            if self.closed:
                raise BudgetExhausted("Audit finished; no further model calls")
            self.in_flight += 1
        try:
            return self._choose(messages, tools)
        finally:
            with self.idle:
                self.in_flight -= 1
                self.idle.notify_all()

    def _choose(self, messages: list[dict], tools: list[dict]) -> ToolCall:
        system, history = messages[0], messages[1:]
        instructions = f"{ROLE_POLICY}\n{system['content']}"
        key = (instructions, tuple(t["function"]["name"] for t in tools))
        if key not in self.drivers:
            driver = self.factory(
                instructions,
                [
                    ToolDefinition(
                        t["function"]["name"],
                        t["function"]["description"],
                        t["function"]["parameters"],
                    )
                    for t in tools
                ],
            )
            if driver is None:
                raise RuntimeError("Model configuration blocked")
            self.drivers[key] = driver
        driver = self.drivers[key]
        if len(json.dumps(history).encode()) > WORKFLOW_LIMITS["historyBytes"]:
            # The Auditor's own working memory limit: end this audit, not the whole workflow.
            raise BudgetExhausted("Auditor history exceeds the workflow history limit")
        try:
            response = self.budget.call(driver, history)
            self.budget.tool()
        except BudgetExceeded:
            self.shared_budget_exhausted = True
            raise BudgetExhausted("Shared workflow budget exhausted") from None
        except Exception as error:
            raise ProviderFailure("openai", safe_provider_diagnostic(error)) from None
        if len(response.calls) != 1:
            raise ToolResponseError("single_function_call_required")
        call = response.calls[0]
        return ToolCall(call.call_id, call.name, native_arguments(call.arguments))


def _limits(budget: SharedBudget) -> Limits:
    left = budget.deadline - time.monotonic()
    calls = WORKFLOW_LIMITS["modelCalls"] - budget.progress.modelCalls
    tools = WORKFLOW_LIMITS["toolCalls"] - budget.progress.toolCalls
    if left <= 1 or calls < 1 or tools < 1:
        raise BudgetExceeded()
    # Leave headroom before the shared deadline to let a timed-out call finish and be counted.
    seconds = min(120.0, left - min(30.0, left / 4))
    return Limits(model_calls=min(16, calls), steps=min(12, tools), seconds=seconds)


def to_model_audit(
    result: AuditResult,
    mapping: Mapping,
    draft: DraftContent,
    session: AuditorSession,
) -> ModelAudit:
    """Map the Auditor's result back into the workflow's ModelAudit (issues never change scores)."""
    issues: list[ModelAuditIssue] = []

    def app_id(issue_id: str, finding_id: str | None) -> str:
        key = f"{issue_id}|{finding_id}"
        session.app_ids.setdefault(key, f"agent-{_digest(issue_id, finding_id)}")
        return session.app_ids[key]

    for issue in result.issues:
        where = " Evidence: " + ", ".join(
            mapping.evidence_refs.get(e, e) for e in issue.evidence_ids
        )
        detail = (
            f"Auditor agent ({issue.kind}, {issue.severity}): {issue.objection}"
            + (where if issue.evidence_ids else "")
        )[:1000]
        for finding_id in issue.finding_ids or [None]:
            student, criterion = mapping.findings.get(finding_id, (None, None))
            issues.append(
                ModelAuditIssue(
                    id=app_id(issue.issue_id, finding_id),
                    studentId=student,
                    criterionId=criterion,
                    detail=detail,
                    kind=KINDS[issue.kind],
                )
            )
    resolved: list[str] = []
    if result.verdict == "audit_passed":
        # A pass is only issued after the harness confirms every audited finding was inspected
        # and every citation verified, with no objection left (pending ones included). So it
        # resolves the Auditor's own earlier open issues on those findings, and its earlier
        # execution issues. Issues raised by other roles are left for them or the professor.
        audited = set(mapping.findings.values())
        resolved = [
            i.id
            for i in draft.audit.issues
            if i.id.startswith("model:agent-")
            and i.disposition == "open"
            and ((i.studentId, i.criterionId) in audited or i.studentId is i.criterionId is None)
        ]
    notes = [
        f"Auditor agent verdict: {result.verdict} ({result.stop_reason}); "
        f"{result.usage['model_calls']} model calls, {result.usage['tool_steps']} tool steps."
    ]
    if result.rejudge_request:
        targets = sorted(
            {":".join(mapping.findings[f]) for f in result.rejudge_request.affected_finding_ids}
        )
        notes.append(
            "Re-judge requested for " + ", ".join(targets) + ": revise with "
            "propose_rubric_assessment, then audit again. Scores are not changed by the Auditor."
        )
    if mapping.excluded:
        notes.append("Not audited by the agent: " + ", ".join(mapping.excluded) + ".")
    if mapping.limitations:
        notes.append("Input limitations: " + "; ".join(mapping.limitations) + ".")
    notes.append("Deterministic checks remain authoritative; an audit pass is not approval.")
    return ModelAudit(
        issues=issues[:100],
        resolvedIssueIds=resolved,
        resolutionReason=(
            "A later Auditor agent pass inspected every audited finding and citation and "
            "raised no remaining objection"
            if resolved
            else "No earlier Auditor objection was resolved in this audit"
        ),
        notes=" ".join(notes)[:1500],
    )


def agent_audit(
    inputs: AssessmentInputs,
    draft: DraftContent,
    evidence: EvidenceMap,
    budget: SharedBudget,
    factory: DriverFactory,
    *,
    session_id: str,
    draft_id: str,
    session: AuditorSession,
) -> ModelAudit:
    """Audit with Le Yong's Auditor agent; fall back to ``model_audit`` if the agent errors."""
    if config.AUDITOR == "model":
        return model_audit(inputs, draft, evidence, budget, factory)
    trace = {
        "role": ROLE_NAME,
        "attempt": 1,
        "instructions": f"{ROLE_POLICY}\n{PROMPT}\n{SCORE_PROMPT}",
        "inputs": {},
        "history": [],
        "schema": {"tools": [t["function"]["name"] for t in TOOLS]},
        "outcome": "started",
        "validation": "pending",
    }
    budget.progress.roleCalls.append(trace)
    budget.checkpoint()
    model = WorkflowModel(budget, factory)
    reason = None
    try:
        mapping = build_request(inputs, draft_id, draft, evidence, session_id, session)
        trace["inputs"] = mapping.request
        session.cases += 0 if mapping.revision else 1
        result = audit_proposal(
            mapping.request,
            model=model,
            evidence_reader=ScopedReader(mapping.request["trusted_scope"], mapping.evidence),
            limits=_limits(budget),
        )
        _settle(model, budget)
        trace.update(
            history=result.trace,
            calls=[e for e in result.trace if e.get("kind") == "tool"],
            output=result.to_dict(),
            validation="AuditResult contract validated",
        )
        if result.stop_reason in FAILED:
            reason = f"Auditor agent stopped with {result.stop_reason}"
            errors = [e for e in result.trace if e.get("kind") == "provider_error"]
            if errors:  # allowlisted category only, never provider error text
                reason += f" ({errors[-1].get('error_category')})"
        else:
            audit = to_model_audit(result, mapping, draft, session)
            session.pending = (
                {
                    "case": result.audit_case_id,
                    "state": asdict(result.updated_state),
                    "finding_ids": sorted(mapping.findings),
                }
                if result.verdict == "rejudge_requested"
                else None
            )
            trace.update(outcome="ok", verdict=result.verdict)
            budget.checkpoint()
    except BudgetExceeded:
        model.settle(budget.deadline - time.monotonic())
        trace.update(outcome="interrupted", reason="Shared workflow budget exhausted")
        budget.checkpoint()
        raise
    except Exception as error:  # the agent errored: record it and fall back
        reason = f"Auditor agent error: {type(error).__name__}"
        if isinstance(error, ContractError):
            reason += f" ({error})"
        _settle(model, budget)
    if reason is None:
        # Outside the fallback boundary: a failed feedback review is a refused audit action,
        # exactly as a failed model_audit was, rather than a reason to discard the agent's audit.
        return _with_feedback_review(audit, inputs, draft, evidence, budget, factory)
    trace.update(outcome="fell_back", reason=reason[:300])
    budget.checkpoint()
    fallback = model_audit(inputs, draft, evidence, budget, factory)
    note = f"Auditor agent unavailable ({reason}); fell back to the single-call model audit. "
    return fallback.model_copy(update={"notes": (note + fallback.notes)[:1500]})


def _settle(model: WorkflowModel, budget: SharedBudget) -> None:
    """Count any in-flight Auditor call before handing control back to the coordinator."""
    if not model.settle(budget.deadline - time.monotonic()) or model.shared_budget_exhausted:
        raise BudgetExceeded()


def _with_feedback_review(
    audit: ModelAudit,
    inputs: AssessmentInputs,
    draft: DraftContent,
    evidence: EvidenceMap,
    budget: SharedBudget,
    factory: DriverFactory,
) -> ModelAudit:
    """The Auditor's contract has no feedback, so a feedback-only role reviews the drafts."""
    if not draft.feedback:
        note = " Feedback review: no feedback drafted yet."
        return audit.model_copy(update={"notes": (audit.notes + note)[:1500]})
    review = feedback_audit(inputs, draft, evidence, budget, factory)
    taken = {i.id for i in audit.issues}
    issues = [*audit.issues, *[i for i in review.issues if i.id not in taken]][:100]
    # The feedback role may resolve earlier non-Auditor model issues; the agent owns its own.
    extra = [r for r in review.resolvedIssueIds if not r.startswith("model:agent-")]
    resolved = list(dict.fromkeys([*audit.resolvedIssueIds, *extra]))
    reason = audit.resolutionReason if audit.resolvedIssueIds else ""
    if extra:
        reason = (reason + " Feedback review: " + review.resolutionReason).strip()
    return ModelAudit(
        issues=issues,
        resolvedIssueIds=resolved,
        resolutionReason=(reason or audit.resolutionReason)[:1000],
        notes=(audit.notes[:900] + " Feedback review: " + review.notes)[:1500],
    )
