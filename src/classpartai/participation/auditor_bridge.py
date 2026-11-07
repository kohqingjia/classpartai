"""Map workflow drafts into the tool-calling Auditor and its results into review issues.

Student-level scores retain their scope. Original turns and actual speaking duration are
preserved; silence is represented without invented turns. Evidence comes only from the
session snapshot. Model calls use the coordinator driver and shared budget. Failures produce
an incomplete audit requiring professor review, never an automatic substitute model pass.

The coordinator uses persisted_agent_audit to reserve and persist the session's one-rejudge
state in SQLite across runs. A crash leaves a fail-closed reservation; there is no automatic
resume or reset. Direct agent_audit callers must supply and preserve their own trusted state.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field

from classpartai import config
from classpartai import usage as ledger
from classpartai.assessment import AssessmentInputs
from classpartai.auditor_agent import audit_proposal
from classpartai.auditor_agent.agent import PROMPT, SCORE_PROMPT, native_arguments
from classpartai.auditor_agent.contracts import (
    AuditRequest,
    AuditResult,
    ContractError,
    Scope,
    reviewed_duration_ms,
)
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
from classpartai.participation.records import Records
from classpartai.participation.roles import (
    ROLE_POLICY,
    DriverFactory,
    feedback_audit,
    model_audit,
)
from classpartai.participation.schema import DraftContent, ModelAudit, ModelAuditIssue
from classpartai.participation.validation import EvidenceMap, Unprocessable

ROLE_NAME = "auditor_agent"
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
    rejudge_used: bool = False
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
                "no_contribution_score": c.noContributionScore,
            }
            for c in inputs.rubric.criteria
        ],
    }
    limitations: list[str] = []

    # Scores are student aggregates; preserve every original turn for contextual comparison.
    contributions, segment_of = [], {}
    for student in inputs.roster:
        own = [
            t
            for t in inputs.transcript.turns
            if t.speaker.kind == "student" and t.speaker.studentId == student.id
        ]
        reviewed = [
            {"turn_id": t.id, "text": t.text, "start_ms": t.startMs, "end_ms": t.endMs} for t in own
        ]
        duration = reviewed_duration_ms(reviewed)
        for turn in own:
            segment_of[turn.id] = turn.id
        contributions.append(
            {
                "contribution_id": f"contribution-{student.id}",
                "turn_ids": [t.id for t in own],
                "student_id": student.id,
                "attribution": "identified",
                "assessment_scope": "student_aggregate" if own else "no_observed_contribution",
                "text": "\n".join(f"[{t.id}] {t.text}" for t in own)
                or (
                    "No observed attributable contribution. "
                    "This is not evidence of poor understanding."
                ),
                "start_ms": min((t.startMs for t in own), default=0),
                "end_ms": max((t.endMs for t in own), default=0),
                "speaking_duration_ms": duration,
                "reviewed_turns": reviewed,
            }
        )
    has_contribution = {c["student_id"] for c in contributions if c["turn_ids"]}

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
        cited = list(dict.fromkeys(segment_of[t] for t in f.turnIds if t in segment_of))
        if not cited and f.studentId in has_contribution:
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
                "transcript_turn_ids": cited,
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
            raise ContractError("Pending rejudge finding set changed; professor review required")
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
    # Never reset lineage or create another allowance on malformed revisions.
    AuditRequest.parse(request)
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

    def __init__(self, budget: SharedBudget, factory: DriverFactory, *, allow_rejudge: bool = True):
        self.allow_rejudge = allow_rejudge
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
        if not self.allow_rejudge:
            tools = [t for t in tools if t["function"]["name"] != "request_rejudge"]
        instructions = f"{ROLE_POLICY}\n{system['content']}"
        if not self.allow_rejudge:
            instructions += (
                "\nThe session rejudge allowance is used. "
                "Escalate remaining issues to the professor."
            )
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
        if call.name == "request_rejudge" and not self.allow_rejudge:
            raise ToolResponseError("rejudge_limit_reached")
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
    if mapping.excluded or mapping.limitations:
        issues.append(
            ModelAuditIssue(
                id="auditor-input-coverage",
                studentId=None,
                criterionId=None,
                kind="uncertainty",
                detail=(
                    "Incomplete Auditor coverage: "
                    + "; ".join(mapping.excluded + mapping.limitations)
                )[:1000],
            )
        )
    resolved: list[str] = []
    open_agent = [
        i for i in draft.audit.issues if i.id.startswith("model:agent-") and i.disposition == "open"
    ]
    if mapping.revision and result.verdict == "audit_passed":
        # Only the linked re-judge round resolves anything: the earlier objections were supplied
        # to the agent as pending state, and the harness passes only when each one is explicitly
        # resolved after re-inspection (and refuses citation removal as a resolution). A fresh
        # case never sees earlier objections, so its pass cannot resolve them.
        pending = AuditRequest.parse(mapping.request).state.pending_rejudge
        keys = {
            f"{o.issue_id}|{finding_id}"
            for o in pending.objections
            for finding_id in o.finding_ids or [None]
        }
        ids = {"model:" + session.app_ids[k] for k in keys if k in session.app_ids}
        resolved = [i.id for i in open_agent if i.id in ids]
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
    still_open = len(open_agent) - len(resolved)
    if still_open:
        notes.append(
            f"{still_open} earlier Auditor issue(s) stay open for professor review: only a linked "
            "re-judge round can resolve them."
        )
    notes.append("Deterministic checks remain authoritative; an audit pass is not approval.")
    return ModelAudit(
        completed=not (mapping.excluded or mapping.limitations),
        issues=capped(issues, 100),
        resolvedIssueIds=resolved,
        resolutionReason=(
            "The Auditor agent re-inspected the re-judged findings and explicitly resolved "
            "each pending objection"
            if resolved
            else "No earlier Auditor objection was resolved in this audit"
        ),
        notes=" ".join(notes)[:1500],
    )


@ledger.tracked("auditor")
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
    """Run the Auditor; failures stay incomplete for explicit professor review."""
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
    model = WorkflowModel(budget, factory, allow_rejudge=not session.rejudge_used)
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
            allow_rejudge=not session.rejudge_used,
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
            if result.rejudge_request:
                if session.rejudge_used:
                    raise ContractError("Session rejudge allowance exhausted")
                session.rejudge_used = True
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
    trace.update(outcome="needs_review", reason=reason[:300])
    budget.checkpoint()
    return _review_required(f"Auditor agent did not complete: {reason}")


def capped(issues: list[ModelAuditIssue], limit: int) -> list[ModelAuditIssue]:
    """At most ``limit`` issues; any overflow is replaced by one visible issue, never dropped
    silently (the full list stays in the role trace)."""
    if len(issues) <= limit:
        return issues
    kept = issues[: limit - 1]
    overflow = issues[limit - 1 :]
    return [
        *kept,
        ModelAuditIssue(
            id=f"overflow-{_digest([i.id for i in overflow])}",
            studentId=None,
            criterionId=None,
            detail=(
                f"{len(overflow)} further audit issue(s) exceed the {limit}-issue limit and are "
                "not listed here; review the Auditor's role trace before approving."
            ),
            kind="uncertainty",
        ),
    ]


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
    # Both reviews keep room: neither may silently push the other's issues past the cap.
    feedback = capped([i for i in review.issues if i.id not in taken], 50)
    issues = [*capped(audit.issues, 100 - len(feedback)), *feedback]
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
        completed=audit.completed and review.completed,
        notes=(audit.notes[:900] + " Feedback review: " + review.notes)[:1500],
    )


def _review_required(reason: str) -> ModelAudit:
    return ModelAudit(
        completed=False,
        issues=[
            ModelAuditIssue(
                id="auditor-incomplete",
                studentId=None,
                criterionId=None,
                detail=reason[:1000],
                kind="uncertainty",
            )
        ],
        resolvedIssueIds=[],
        resolutionReason="No Auditor objections were resolved",
        notes=reason[:1500] + ". No substitute audit was performed; professor review is required.",
    )


def persisted_agent_audit(*args, records: Records, session_id: str, **kwargs) -> ModelAudit:
    """Persist case lineage and serialize audits across coordinator runs and connections.

    A process crash leaves the reservation in place: it never silently grants another round.
    """
    try:
        reservation, state = records.claim_auditor(session_id)
    except Unprocessable:
        return _review_required(
            "Auditor reservation active or interrupted; professor review required"
        )
    session = AuditorSession(**state)
    try:
        return agent_audit(*args, session_id=session_id, session=session, **kwargs)
    finally:
        records.finish_auditor(session_id, reservation, asdict(session))
