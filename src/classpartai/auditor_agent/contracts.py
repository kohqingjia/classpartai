"""Version 1 JSON-compatible contracts. No dependency on the application or a model SDK."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from typing import Any


class ContractError(ValueError):
    """Untrusted input does not satisfy the public contract."""


def obj(value: Any, required: set[str], optional: set[str] | None = None) -> dict:
    if (
        not isinstance(value, dict)
        or set(value) - required - (optional or set())
        or required - set(value)
    ):
        raise ContractError("Object has missing or unknown fields")
    return value


def text(value: Any, limit: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError("Expected a nonempty bounded string")
    return value


def identifier(value: Any) -> str:
    value = text(value, 100)
    if not all(c.isascii() and (c.isalnum() or c in "-_.:") for c in value):
        raise ContractError("IDs must use ASCII letters, numbers, dash, underscore, dot or colon")
    return value


def number(value: Any, low: float, high: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not low <= value <= high
    ):
        raise ContractError("Number outside permitted range")
    return float(value)


def integer(value: Any, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise ContractError("Integer outside permitted range")
    return value


def array(value: Any, maximum: int = 100, minimum: int = 0) -> list:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise ContractError("List outside permitted bounds")
    return value


def ids(value: Any, maximum: int = 100, minimum: int = 0) -> list[str]:
    result = [identifier(v) for v in array(value, maximum, minimum)]
    if len(result) != len(set(result)):
        raise ContractError("Duplicate IDs")
    return result


def version(value: Any) -> None:
    if type(value) is not int or value != 1:
        raise ContractError("Unsupported schema_version (expected 1)")


@dataclass(frozen=True)
class Scope:
    course_id: str
    session_id: str

    @classmethod
    def parse(cls, data: Any) -> Scope:
        d = obj(data, {"course_id", "session_id"})
        return cls(identifier(d["course_id"]), identifier(d["session_id"]))


@dataclass(frozen=True)
class ProposalRef:
    proposal_id: str
    version: int

    @classmethod
    def parse(cls, data: Any) -> ProposalRef:
        d = obj(data, {"proposal_id", "version"})
        return cls(identifier(d["proposal_id"]), integer(d["version"], 1, 100000))


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    description: str
    minimum: float
    maximum: float
    no_contribution_score: float | None = None

    @classmethod
    def parse(cls, data: Any) -> Criterion:
        d = obj(
            data, {"criterion_id", "description", "minimum", "maximum"}, {"no_contribution_score"}
        )
        low = number(d["minimum"], -1000, 1000)
        high = number(d["maximum"], low, 1000)
        return cls(
            identifier(d["criterion_id"]),
            text(d["description"]),
            low,
            high,
            None
            if d.get("no_contribution_score") is None
            else number(d["no_contribution_score"], low, high),
        )


@dataclass(frozen=True)
class Rubric:
    rubric_id: str
    version: str
    criteria: list[Criterion]

    @classmethod
    def parse(cls, data: Any) -> Rubric:
        d = obj(data, {"rubric_id", "version", "criteria"})
        criteria = [Criterion.parse(c) for c in array(d["criteria"], 12, 1)]
        unique([c.criterion_id for c in criteria])
        return cls(identifier(d["rubric_id"]), identifier(d["version"]), criteria)


@dataclass(frozen=True)
class Contribution:
    contribution_id: str
    turn_ids: list[str]
    student_id: str | None
    attribution: str
    text: str
    start_ms: int
    end_ms: int
    # Legacy input only: retained for old callers and case fingerprints, never analysed.
    transcription_confidence: float | None = None
    speaking_duration_ms: int | None = None
    reviewed_turns: list[dict] | None = None
    assessment_scope: str = "contribution"
    # The Listener's injection screen over this contribution's own turns (classpartai/injection.py):
    # "suspected_instruction" when a turn tries to instruct the grader. The Auditor trusts this flag
    # instead of re-scanning the text, so a transcript is screened once, at the earliest stage.
    listener_injection: str | None = None

    @classmethod
    def parse(cls, data: Any) -> Contribution:
        d = obj(
            data,
            {
                "contribution_id",
                "turn_ids",
                "student_id",
                "attribution",
                "text",
                "start_ms",
                "end_ms",
            },
            {
                "speaking_duration_ms",
                "reviewed_turns",
                "assessment_scope",
                "transcription_confidence",
                "listener_injection",
            },
        )
        if d["attribution"] not in ("identified", "uncertain", "unknown"):
            raise ContractError("Unknown attribution status")
        student = identifier(d["student_id"]) if d["student_id"] is not None else None
        if (d["attribution"] == "identified") != (student is not None):
            raise ContractError("Uncertain attribution must not silently credit a student")
        start = integer(d["start_ms"], 0, 86400000)
        scope = d.get("assessment_scope", "contribution")
        if scope not in ("contribution", "student_aggregate", "no_observed_contribution"):
            raise ContractError("Unknown assessment scope")
        turn_ids = ids(d["turn_ids"], 5000, 0 if scope == "no_observed_contribution" else 1)
        if scope == "no_observed_contribution" and turn_ids:
            raise ContractError("No-observation records cannot invent transcript references")
        turns = d.get("reviewed_turns")
        if turns is not None:
            for turn in array(turns, 5000):
                obj(turn, {"turn_id", "text", "start_ms", "end_ms"})
                identifier(turn["turn_id"])
                text(turn["text"], 20000)
                integer(turn["end_ms"], integer(turn["start_ms"], 0, 86400000), 86400000)
            if [t["turn_id"] for t in turns] != turn_ids:
                raise ContractError("Reviewed turns must preserve the original turn IDs")
        duration = d.get("speaking_duration_ms")
        if duration is not None:
            integer(duration, 0, 86400000)
            if turns is not None and duration != reviewed_duration_ms(turns):
                raise ContractError("Speaking duration must match reviewed intervals")
        if scope != "contribution" and (turns is None or duration is None):
            raise ContractError(
                "Aggregate and no-observation records need explicit duration metadata"
            )
        return cls(
            identifier(d["contribution_id"]),
            turn_ids,
            student,
            d["attribution"],
            text(d["text"], 100000),
            start,
            integer(d["end_ms"], start, 86400000),
            None
            if d.get("transcription_confidence") is None
            else number(d["transcription_confidence"], 0, 1),
            duration,
            turns,
            scope,
            None if d.get("listener_injection") is None else text(d["listener_injection"], 40),
        )


@dataclass(frozen=True)
class EvidenceRef:
    evidence_id: str
    source_id: str
    source_version: str
    passage_id: str
    page: int
    quote: str

    @classmethod
    def parse(cls, data: Any) -> EvidenceRef:
        d = obj(data, {"evidence_id", "source_id", "source_version", "passage_id", "page", "quote"})
        return cls(
            identifier(d["evidence_id"]),
            identifier(d["source_id"]),
            identifier(d["source_version"]),
            identifier(d["passage_id"]),
            integer(d["page"], 1, 100000),
            text(d["quote"], 4000),
        )


@dataclass(frozen=True)
class Finding:
    finding_id: str
    contribution_id: str
    criterion_id: str
    score: float | None
    rationale: str
    transcript_turn_ids: list[str]
    evidence: list[EvidenceRef]

    @classmethod
    def parse(cls, data: Any) -> Finding:
        d = obj(
            data,
            {
                "finding_id",
                "contribution_id",
                "criterion_id",
                "score",
                "rationale",
                "transcript_turn_ids",
                "evidence",
            },
        )
        refs = [EvidenceRef.parse(e) for e in array(d["evidence"], 6)]
        unique([e.evidence_id for e in refs])
        return cls(
            identifier(d["finding_id"]),
            identifier(d["contribution_id"]),
            identifier(d["criterion_id"]),
            None if d["score"] is None else number(d["score"], -1000, 1000),
            text(d["rationale"]),
            ids(d["transcript_turn_ids"], 30, 0),
            refs,
        )


@dataclass(frozen=True)
class JudgeProposal:
    schema_version: int
    reference: ProposalRef
    previous_proposal: ProposalRef | None
    rejudge_request_id: str | None
    rubric_id: str
    rubric_version: str
    findings: list[Finding]

    @classmethod
    def parse(cls, data: Any) -> JudgeProposal:
        d = obj(
            data,
            {
                "schema_version",
                "reference",
                "previous_proposal",
                "rejudge_request_id",
                "rubric_id",
                "rubric_version",
                "findings",
            },
        )
        version(d["schema_version"])
        findings = [Finding.parse(f) for f in array(d["findings"], 60, 1)]
        unique([f.finding_id for f in findings])
        return cls(
            1,
            ProposalRef.parse(d["reference"]),
            None if d["previous_proposal"] is None else ProposalRef.parse(d["previous_proposal"]),
            None if d["rejudge_request_id"] is None else identifier(d["rejudge_request_id"]),
            identifier(d["rubric_id"]),
            identifier(d["rubric_version"]),
            findings,
        )


@dataclass(frozen=True)
class Issue:
    issue_id: str
    kind: str
    severity: str
    finding_ids: list[str]
    evidence_ids: list[str]
    objection: str

    @classmethod
    def parse(cls, data: Any) -> Issue:
        d = obj(data, {"issue_id", "kind", "severity", "finding_ids", "evidence_ids", "objection"})
        if d["kind"] not in (
            "citation",
            "consistency",
            "injection",
            "attribution",
            "fairness",
            "rationale",
            "missing_evidence",
            "execution",
        ) or d["severity"] not in ("material", "review"):
            raise ContractError("Invalid issue classification")
        return cls(
            identifier(d["issue_id"]),
            d["kind"],
            d["severity"],
            ids(d["finding_ids"], 60),
            ids(d["evidence_ids"], 100),
            text(d["objection"]),
        )


@dataclass(frozen=True)
class RejudgeRequest:
    schema_version: int
    audit_case_id: str
    original_proposal: ProposalRef
    request_id: str
    affected_finding_ids: list[str]
    affected_criterion_ids: list[str]
    objections: list[Issue]
    evidence_ids: list[str]

    @classmethod
    def parse(cls, data: Any) -> RejudgeRequest:
        d = obj(
            data,
            {
                "schema_version",
                "audit_case_id",
                "original_proposal",
                "request_id",
                "affected_finding_ids",
                "affected_criterion_ids",
                "objections",
                "evidence_ids",
            },
        )
        version(d["schema_version"])
        return cls(
            1,
            identifier(d["audit_case_id"]),
            ProposalRef.parse(d["original_proposal"]),
            identifier(d["request_id"]),
            ids(d["affected_finding_ids"], 60, 1),
            ids(d["affected_criterion_ids"], 12, 1),
            [Issue.parse(i) for i in array(d["objections"], 300, 1)],
            ids(d["evidence_ids"], 600),
        )


@dataclass(frozen=True)
class AuditState:
    schema_version: int
    audit_case_id: str
    scope: Scope
    rubric_id: str
    rubric_version: str
    state_version: int
    rejudge_count: int
    last_proposal: ProposalRef | None
    pending_rejudge: RejudgeRequest | None
    terminal: bool
    input_fingerprint: str | None
    finding_bindings: dict

    @classmethod
    def parse(cls, data: Any) -> AuditState:
        d = obj(
            data,
            {
                "schema_version",
                "audit_case_id",
                "scope",
                "rubric_id",
                "rubric_version",
                "state_version",
                "rejudge_count",
                "last_proposal",
                "pending_rejudge",
                "terminal",
                "input_fingerprint",
                "finding_bindings",
            },
        )
        version(d["schema_version"])
        if type(d["terminal"]) is not bool:
            raise ContractError("Expected boolean terminal state")
        bindings = d["finding_bindings"]
        if not isinstance(bindings, dict) or len(bindings) > 60:
            raise ContractError("Invalid finding bindings")
        for key, value in bindings.items():
            identifier(key)
            for item in array(value, 2, 2):
                identifier(item)
        return cls(
            1,
            identifier(d["audit_case_id"]),
            Scope.parse(d["scope"]),
            identifier(d["rubric_id"]),
            identifier(d["rubric_version"]),
            integer(d["state_version"], 0, 100000),
            integer(d["rejudge_count"], 0, 1),
            None if d["last_proposal"] is None else ProposalRef.parse(d["last_proposal"]),
            None if d["pending_rejudge"] is None else RejudgeRequest.parse(d["pending_rejudge"]),
            d["terminal"],
            None if d["input_fingerprint"] is None else identifier(d["input_fingerprint"]),
            bindings,
        )


@dataclass(frozen=True)
class AuditRequest:
    schema_version: int
    audit_case_id: str
    trusted_scope: Scope
    rubric: Rubric
    contributions: list[Contribution]
    proposal: JudgeProposal
    state: AuditState

    @classmethod
    def parse(cls, data: Any) -> AuditRequest:
        # Reject huge inputs before spending model calls. JSON only, no NaN or custom objects.
        try:
            encoded = json.dumps(data, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ContractError("Request must be finite JSON data") from exc
        if len(encoded.encode()) > 150000:
            raise ContractError("Request exceeds 150 KB")
        d = obj(
            data,
            {
                "schema_version",
                "audit_case_id",
                "trusted_scope",
                "rubric",
                "contributions",
                "proposal",
                "state",
            },
        )
        version(d["schema_version"])
        result = cls(
            1,
            identifier(d["audit_case_id"]),
            Scope.parse(d["trusted_scope"]),
            Rubric.parse(d["rubric"]),
            [Contribution.parse(c) for c in array(d["contributions"], 40, 1)],
            JudgeProposal.parse(d["proposal"]),
            AuditState.parse(d["state"]),
        )
        result.validate()
        return result

    def validate(self) -> None:
        s, p = self.state, self.proposal
        if s.terminal or (s.audit_case_id, s.scope, s.rubric_id, s.rubric_version) != (
            self.audit_case_id,
            self.trusted_scope,
            self.rubric.rubric_id,
            self.rubric.version,
        ):
            raise ContractError("Case is terminal or trusted state/scope differs")
        if (p.rubric_id, p.rubric_version) != (self.rubric.rubric_id, self.rubric.version):
            raise ContractError("Proposal changed rubric version")
        unique([c.contribution_id for c in self.contributions])
        unique([t for c in self.contributions for t in c.turn_ids])
        pairs = []
        for f in p.findings:
            c = next(
                (c for c in self.contributions if c.contribution_id == f.contribution_id), None
            )
            criterion = next(
                (c for c in self.rubric.criteria if c.criterion_id == f.criterion_id), None
            )
            if c is None or criterion is None or not set(f.transcript_turn_ids) <= set(c.turn_ids):
                raise ContractError("Unknown contribution, criterion or transcript reference")
            if c.assessment_scope == "no_observed_contribution" and f.score is not None:
                if (
                    criterion.no_contribution_score is None
                    or f.score != criterion.no_contribution_score
                ):
                    raise ContractError(
                        "No observed contribution permits only an explicit rubric score"
                    )
            if not f.transcript_turn_ids and c.assessment_scope != "no_observed_contribution":
                raise ContractError("Observed findings require transcript references")
            if f.score is not None and not criterion.minimum <= f.score <= criterion.maximum:
                raise ContractError("Score outside pinned rubric range")
            pairs.append((f.contribution_id, f.criterion_id))
        unique(pairs)
        evidence = [asdict(e) for f in p.findings for e in f.evidence]
        for ref in evidence:
            if any(e["evidence_id"] == ref["evidence_id"] and e != ref for e in evidence):
                raise ContractError("Conflicting evidence IDs")
        if s.rejudge_count == 0:
            if (
                s.input_fingerprint is not None
                or s.finding_bindings
                or s.state_version != 0
                or s.last_proposal
                or s.pending_rejudge
                or p.previous_proposal
                or p.rejudge_request_id
            ):
                raise ContractError("Invalid initial round state")
        else:
            if s.input_fingerprint != input_fingerprint(self) or s.finding_bindings != {
                f.finding_id: [f.contribution_id, f.criterion_id] for f in p.findings
            }:
                raise ContractError("Revision changed immutable audit inputs or finding identities")
            r = s.pending_rejudge
            if (
                s.state_version != 1
                or not r
                or s.last_proposal != r.original_proposal
                or r.audit_case_id != self.audit_case_id
                or p.previous_proposal != s.last_proposal
                or p.rejudge_request_id != r.request_id
                or p.reference.version != s.last_proposal.version + 1
                or p.reference.proposal_id != s.last_proposal.proposal_id
            ):
                raise ContractError("Revision lineage or one-round state invalid")
            if not set(r.affected_finding_ids) <= {f.finding_id for f in p.findings}:
                raise ContractError("Revision removed affected findings")
            validate_issues(r.objections, self)
            if (
                set(r.affected_finding_ids) != {fid for i in r.objections for fid in i.finding_ids}
                or set(r.affected_criterion_ids)
                != {f.criterion_id for f in p.findings if f.finding_id in r.affected_finding_ids}
                or set(r.evidence_ids) != {eid for i in r.objections for eid in i.evidence_ids}
            ):
                raise ContractError("Rejudge handoff references differ from objections")


def input_fingerprint(request: AuditRequest) -> str:
    import hashlib

    contributions = []
    for contribution in request.contributions:
        data = asdict(contribution)
        # Preserve fingerprints for v1 callers that do not supply aggregate metadata.
        if (
            contribution.assessment_scope == "contribution"
            and contribution.speaking_duration_ms is None
            and contribution.reviewed_turns is None
        ):
            for field in ("assessment_scope", "speaking_duration_ms", "reviewed_turns"):
                data.pop(field)
        if data["listener_injection"] is None:
            data.pop("listener_injection")  # fingerprints of callers without the flag are kept
        contributions.append(data)
    rubric = asdict(request.rubric)
    for criterion in rubric["criteria"]:
        if criterion["no_contribution_score"] is None:
            criterion.pop("no_contribution_score")
    return hashlib.sha256(json.dumps([rubric, contributions], sort_keys=True).encode()).hexdigest()


def unique(values: list) -> None:
    if len(values) != len(set(values)):
        raise ContractError("Duplicate stable reference")


def validate_issues(issues: list[Issue], request: AuditRequest) -> None:
    unique([i.issue_id for i in issues])
    findings = {f.finding_id for f in request.proposal.findings}
    evidence = {e.evidence_id for f in request.proposal.findings for e in f.evidence}
    # A revised Judge may remove a bad citation; earlier objections remain valid history.
    if request.state.pending_rejudge:
        evidence.update(request.state.pending_rejudge.evidence_ids)
    for issue in issues:
        if not set(issue.finding_ids) <= findings or not set(issue.evidence_ids) <= evidence:
            raise ContractError("Issue references unknown findings or evidence")


@dataclass(frozen=True)
class AuditResult:
    schema_version: int
    audit_case_id: str
    audited_proposal: ProposalRef
    verdict: str
    issues: list[Issue]
    affected_finding_ids: list[str]
    supporting_evidence_ids: list[str]
    trace_reference: str
    stop_reason: str
    updated_state: AuditState
    rejudge_request: RejudgeRequest | None
    trace: list[dict]
    usage: dict

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def parse(cls, data: Any) -> AuditResult:
        d = obj(data, set(cls.__dataclass_fields__))
        version(d["schema_version"])
        if d["verdict"] not in ("audit_passed", "rejudge_requested", "professor_review_required"):
            raise ContractError("Invalid verdict")
        result = cls(
            1,
            identifier(d["audit_case_id"]),
            ProposalRef.parse(d["audited_proposal"]),
            d["verdict"],
            [Issue.parse(i) for i in array(d["issues"], 300)],
            ids(d["affected_finding_ids"]),
            ids(d["supporting_evidence_ids"], 600),
            identifier(d["trace_reference"]),
            identifier(d["stop_reason"]),
            AuditState.parse(d["updated_state"]),
            None if d["rejudge_request"] is None else RejudgeRequest.parse(d["rejudge_request"]),
            array(d["trace"], 100),
            obj(
                d["usage"],
                {"model_calls", "tool_steps", "elapsed_ms", "tokens", "token_accounting"},
            ),
        )
        state = result.updated_state
        if (
            state.audit_case_id != result.audit_case_id
            or state.last_proposal != result.audited_proposal
            or (result.verdict == "rejudge_requested") != (result.rejudge_request is not None)
            or state.terminal != (result.verdict != "rejudge_requested")
        ):
            raise ContractError("Result/state transition differs")
        unique([i.issue_id for i in result.issues])
        if set(result.affected_finding_ids) != {f for i in result.issues for f in i.finding_ids}:
            raise ContractError("Result affected findings differ from issues")
        integer(result.usage["model_calls"], 0, 40)
        integer(result.usage["tool_steps"], 0, 30)
        number(result.usage["elapsed_ms"], 0, 1e9)
        if result.verdict == "audit_passed" and result.issues:
            raise ContractError("Pass cannot contain unresolved issues")
        if result.rejudge_request and (
            state.rejudge_count != 1 or state.pending_rejudge != result.rejudge_request
        ):
            raise ContractError("Result rejudge state differs")
        return result


def reviewed_duration_ms(turns: list[dict]) -> int:
    """Union of a speaker's reviewed intervals: exclude gaps and count overlaps once."""
    duration, right = 0, 0
    for start, end in sorted((t["start_ms"], t["end_ms"]) for t in turns):
        duration += max(0, end - max(start, right))
        right = max(right, end)
    return duration
