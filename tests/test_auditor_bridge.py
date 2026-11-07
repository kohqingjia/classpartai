"""The workflow's audit step through Le Yong's Auditor agent, with scripted fakes (no network)."""

import threading
import time

import conftest
import pytest
from conftest import SILENT, ScriptedDriver, full_proposal, judge_steps
from test_coordinator import AUDIT, fb

from classpartai import config
from classpartai.evidence import Citation, EvidenceBundle
from classpartai.models import WORKFLOW_LIMITS, BudgetExceeded, SharedBudget, WorkflowProgress
from classpartai.participation.auditor_bridge import AuditorSession, agent_audit, build_request
from classpartai.participation.coordinator import coordinate
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import compose_draft

READ = ("get_session_scores", {"offset": 0, "limit": 10})
FEEDBACK_OK = (
    "finish_feedback_audit",
    {"issues": [], "resolvedIssueIds": [], "resolutionReason": "n/a", "notes": "Feedback fits."},
)


def factory_for(scripts):
    """conftest.factory_for plus a feedback-review script, which runs after the agent."""
    scripts.setdefault("finish_feedback_audit", ScriptedDriver([FEEDBACK_OK] * 5))
    return conftest.factory_for(scripts)


def finish(verdict="audit_passed", resolved=()):
    return ("complete_audit", {"verdict": verdict, "issues": [], "resolved_issue_ids": [*resolved]})


def objection(issue_id="alex-overstated"):
    return {
        "issue_id": issue_id,
        "kind": "rationale",
        "severity": "material",
        "finding_ids": ["alex-tan:reasoning"],
        "evidence_ids": [],
        "objection": "The rationale does not show how the turn meets the top rubric level.",
    }


@pytest.fixture
def benign(inputs):
    """The sample session without its deliberate grader-instruction turn."""
    copy = inputs.model_copy(deep=True)
    copy.transcript.turns[5].text = "Self-RAG grades its own retrieved passages."
    return copy


def budget():
    return SharedBudget(WorkflowProgress(), time.monotonic() + 600)


def draft_of(inputs, previous=None, audit=None):
    return compose_draft(Proposal.model_validate(full_proposal()), inputs, "test", previous, audit)


def run(inputs, draft, factory, b=None, session=None, evidence=()):
    return agent_audit(
        inputs,
        draft,
        list(evidence),
        b or budget(),
        factory,
        session_id="session-1",
        draft_id="draft-1",
        session=session or AuditorSession(),
    )


def test_request_maps_workflow_data_and_marks_what_it_cannot_express(benign):
    mapping = build_request(benign, "d", draft_of(benign), [], "session-1", AuditorSession())
    request = mapping.request
    # One contribution per speaking student, own turns only, no invented ASR confidence.
    assert [c["student_id"] for c in request["contributions"]] == [
        "alex-tan",
        "priya-nair",
        "jordan-wong",
    ]
    alex = request["contributions"][0]
    assert alex["turn_ids"] == ["turn-002", "turn-005"]
    assert alex["transcription_confidence"] is None
    assert alex["attribution"] == "identified"
    # Marcus has no turns, so his findings are listed as not audited rather than given turns.
    assert {f["finding_id"] for f in request["proposal"]["findings"]} == {
        f"{s}:{c}"
        for s in ("alex-tan", "priya-nair", "jordan-wong")
        for c in ("reasoning", "engagement")
    }
    assert mapping.excluded == [
        "marcus-lee:reasoning (no attributable turns)",
        "marcus-lee:engagement (no attributable turns)",
    ]
    assert request["rubric"]["criteria"][0]["maximum"] == 3


def test_many_turns_are_grouped_into_twelve_segments(benign):
    copy = benign.model_copy(deep=True)
    template = copy.transcript.turns[1]
    copy.transcript.turns += [
        template.model_copy(update={"id": f"turn-x{n}", "text": f"Point {n}."}) for n in range(20)
    ]
    mapping = build_request(copy, "d", draft_of(copy), [], "session-1", AuditorSession())
    alex = mapping.request["contributions"][0]
    assert len(alex["turn_ids"]) == 11  # 22 turns, two per segment
    assert "[turn-x19] Point 19." in alex["text"]
    assert any("grouped into" in note for note in mapping.limitations)


def test_audit_raises_issues_never_changes_scores_and_counts_the_shared_budget(inputs):
    agent = ScriptedDriver([READ, finish()])
    b = budget()
    draft = draft_of(inputs)
    audit = run(inputs, draft, factory_for({"get_session_scores": agent}), b)
    # The deliberate grader-instruction turn is caught by the Auditor's guard, so its pass is
    # refused and the issue goes to the professor; scores are untouched.
    flagged = {(i.studentId, i.criterionId, i.kind) for i in audit.issues}
    assert flagged == {
        ("jordan-wong", "reasoning", "uncertainty"),
        ("jordan-wong", "engagement", "uncertainty"),
    }
    assert all(i.detail.startswith("Auditor agent (injection, review)") for i in audit.issues)
    assert "professor_review_required" in audit.notes
    assert "marcus-lee:reasoning (no attributable turns)" in audit.notes
    assert draft.findings == Proposal.model_validate(full_proposal()).findings
    assert (b.progress.modelCalls, b.progress.toolCalls, b.progress.tokens) == (3, 3, 30)
    trace = b.progress.roleCalls[-2]  # then the feedback review
    assert b.progress.roleCalls[-1]["role"] == "finish_feedback_audit"
    assert (trace["role"], trace["outcome"], trace["verdict"]) == (
        "auditor_agent",
        "ok",
        "professor_review_required",
    )
    assert "untrusted" in agent.histories[0][0]["content"].lower()


def test_rejudge_then_revision_resolves_the_original_objection(benign):
    session = AuditorSession()
    first = run(
        benign,
        draft_of(benign),
        factory_for(
            {
                "get_session_scores": ScriptedDriver(
                    [READ, ("request_rejudge", {"issues": [objection()]})]
                )
            }
        ),
        session=session,
    )
    assert [(i.studentId, i.criterionId, i.kind) for i in first.issues] == [
        ("alex-tan", "reasoning", "support")
    ]
    assert "Re-judge requested for alex-tan:reasoning" in first.notes
    assert first.resolvedIssueIds == []
    audited = draft_of(benign, draft_of(benign), first)
    revised = draft_of(benign, audited)  # the Judge's revision keeps the open model issue
    app_id = "model:" + first.issues[0].id
    assert any(i.id == app_id and i.disposition == "open" for i in revised.audit.issues)

    b = budget()
    second = run(
        benign,
        revised,
        factory_for(
            {"get_session_scores": ScriptedDriver([READ, finish(resolved=["alex-overstated"])])}
        ),
        b,
        session,
    )
    request = b.progress.roleCalls[-2]["inputs"]
    assert request["proposal"]["reference"]["version"] == 2  # submitted as the revision
    assert request["state"]["rejudge_count"] == 1
    assert second.issues == [] and second.resolvedIssueIds == [app_id]
    final = draft_of(benign, revised, second)
    assert next(i for i in final.audit.issues if i.id == app_id).disposition == "revised"
    assert session.pending is None


def test_citations_are_verified_against_the_sessions_own_passages(benign):
    passage = benign.documents[0].passages[0]
    bundle = EvidenceBundle(
        sessionId="session-1",
        question="Why might an agent help?",
        transcriptVersion=benign.transcript.version,
        rubric={"id": benign.rubric.id, "version": benign.rubric.version},
        status="sufficient",
        explanation="Supports the point about vague questions.",
        turnIds=["turn-002"],
        citations=[
            Citation(
                passageId="w10-agentic-rag:p1",
                documentId=benign.documents[0].id,
                version=benign.documents[0].version,
                title=benign.documents[0].title,
                source=benign.documents[0].source,
                passageKey=passage.id,
                page=passage.page,
                excerpt="It struggles when the question is vague",
                relevance="Explains why single-pass retrieval fails",
                relationship="supports",
            )
        ],
        conflicts=[],
        gaps=[],
    )
    raw = full_proposal()
    raw["findings"][0]["citations"] = [
        {"evidenceRunId": "run-1", "passageId": "w10-agentic-rag:p1"}
    ]
    draft = compose_draft(Proposal.model_validate(raw), benign, "test")
    reviewer = ScriptedDriver(
        [
            (
                "citation_assessment",
                {
                    "relationship": "supports",
                    "quote": "It struggles when the question is vague",
                    "explanation": "The passage supports the rationale's claim.",
                },
            )
        ]
    )
    agent = ScriptedDriver(
        [
            READ,
            ("verify_citation", {"finding_id": "alex-tan:reasoning", "evidence_id": "evidence-1"}),
            finish(),
        ]
    )
    b = budget()
    audit = run(
        benign,
        draft,
        factory_for({"get_session_scores": agent, "citation_assessment": reviewer}),
        b,
        evidence=[("run-1", bundle)],
    )
    assert audit.issues == []
    assert "audit_passed" in audit.notes
    assert passage.text in reviewer.histories[0][0]["content"]  # read from the session's docs
    assert b.progress.modelCalls == 5  # nested citation review and feedback review count


def test_agent_error_falls_back_to_single_call_audit_and_says_so(inputs):
    def broken(instructions, tools):
        if any(t.name == "get_session_scores" for t in tools):
            raise RuntimeError("provider down")
        return ScriptedDriver([("finish_assessment_audit", AUDIT)])

    b = budget()
    audit = run(inputs, draft_of(inputs), broken, b)
    assert audit.notes.startswith("Auditor agent unavailable")
    assert "fell back to the single-call model audit" in audit.notes
    assert [i.id for i in audit.issues] == ["injection"]
    roles = [(c["role"], c["outcome"]) for c in b.progress.roleCalls]
    assert roles == [("auditor_agent", "fell_back"), ("finish_assessment_audit", "ok")]


def test_shared_budget_exhaustion_stops_the_workflow_without_fallback(inputs):
    b = budget()
    b.progress.tokens = WORKFLOW_LIMITS["tokens"] - 5  # the next call cannot fit
    agent = ScriptedDriver([READ, finish()])
    with pytest.raises(BudgetExceeded):
        run(inputs, draft_of(inputs), factory_for({"get_session_scores": agent}), b)
    assert agent.histories == []
    assert [c["role"] for c in b.progress.roleCalls] == ["auditor_agent"]
    assert b.progress.roleCalls[0]["outcome"] == "interrupted"


def test_auditor_limits_are_capped_by_what_is_left_of_the_shared_budget(inputs):
    b = budget()
    b.progress.modelCalls = WORKFLOW_LIMITS["modelCalls"] - 1  # room for one Auditor call
    agent = ScriptedDriver([READ, finish()])
    no_feedback = compose_draft(
        Proposal(findings=Proposal.model_validate(full_proposal()).findings, feedback=[]),
        inputs,
        "test",
    )
    audit = run(inputs, no_feedback, factory_for({"get_session_scores": agent}), b)
    assert b.progress.modelCalls == WORKFLOW_LIMITS["modelCalls"]
    assert "no feedback drafted yet" in audit.notes
    assert "budget_exhausted" in audit.notes
    assert any("budget exhausted" in i.detail for i in audit.issues)


def test_model_setting_skips_the_agent(inputs, monkeypatch):
    monkeypatch.setattr(config, "AUDITOR", "model")
    b = budget()
    audit = run(
        inputs,
        draft_of(inputs),
        factory_for(
            {"finish_assessment_audit": ScriptedDriver([("finish_assessment_audit", AUDIT)])}
        ),
        b,
    )
    assert [i.id for i in audit.issues] == ["injection"]
    assert [c["role"] for c in b.progress.roleCalls] == ["finish_assessment_audit"]


def test_coordinator_runs_the_auditor_agent_end_to_end(records, session_id):
    coordinator = ScriptedDriver(
        [
            ("propose_rubric_assessment", {"note": "First pass"}),
            *[
                ("draft_student_feedback", {"studentId": s})
                for s in ("alex-tan", "priya-nair", "jordan-wong", "marcus-lee")
            ],
            ("audit_assessment", {"note": "Audit"}),
            ("request_professor_review", {"summary": "Ready, injection flagged"}),
        ]
    )
    roles = factory_for(
        {
            "inspect_transcript_context": coordinator,
            "score_contribution": ScriptedDriver(judge_steps()),
            "finish_student_feedback": ScriptedDriver(
                [
                    ("finish_student_feedback", fb("alex-tan")),
                    ("finish_student_feedback", fb("priya-nair")),
                    ("finish_student_feedback", fb("jordan-wong")),
                    ("finish_student_feedback", fb("marcus-lee", SILENT)),
                ]
            ),
            "get_session_scores": ScriptedDriver([READ, finish()]),
        }
    )
    coordinate(records, session_id, roles)
    run_record = records.runs(session_id)[0]
    assert run_record["stop_reason"] == "ready_for_professor_review"
    draft = records.latest_draft(session_id)
    assert draft.content.audit.modelReviewed
    assert "Auditor agent verdict" in draft.content.audit.notes
    agent_issues = [i for i in draft.content.audit.issues if i.id.startswith("model:agent-")]
    assert {i.studentId for i in agent_issues} == {"jordan-wong"}
    assert all(i.severity == "review" for i in agent_issues)
    # Deterministic issues are still there alongside the Auditor's.
    assert "attribution:uncertain" in [i.id for i in draft.content.audit.issues]
    progress = run_record["progress"]
    assert progress["modelCalls"] == 7 + 1 + 4 + 2 + 1  # coordinator, judge, feedback, Auditor
    assert [c["role"] for c in progress["roleCalls"]][-2:] == [
        "auditor_agent",
        "finish_feedback_audit",
    ]


def test_feedback_drafts_still_get_a_semantic_review(benign):
    raw = full_proposal()
    claim = "You correctly explained how fine-tuning updates neural network weights."
    raw["feedback"][0]["strengths"] = claim
    draft = compose_draft(Proposal.model_validate(raw), benign, "test")
    issue = {
        "id": "alex-feedback",
        "studentId": "alex-tan",
        "criterionId": None,
        "detail": "Strength credits a point Alex never made.",
        "kind": "feedback",
    }
    review = ScriptedDriver(
        [
            (
                "finish_feedback_audit",
                {**FEEDBACK_OK[1], "issues": [issue], "notes": "One unsupported strength."},
            )
        ]
    )
    audit = run(
        benign,
        draft,
        factory_for(
            {
                "get_session_scores": ScriptedDriver([READ, finish()]),
                "finish_feedback_audit": review,
            }
        ),
    )
    assert claim in review.histories[0][0]["content"]  # the reviewer saw the feedback
    assert [(i.id, i.kind) for i in audit.issues] == [("alex-feedback", "feedback")]
    assert "audit_passed" in audit.notes and "One unsupported strength." in audit.notes
    final = compose_draft(Proposal.model_validate(raw), benign, "audited", draft, audit)
    assert any(
        i.id == "model:alex-feedback" and i.disposition == "open" for i in final.audit.issues
    )


def test_a_fresh_pass_never_resolves_an_objection_it_was_not_shown(benign):
    session = AuditorSession()
    escalate = (
        "complete_audit",
        {"verdict": "professor_review_required", "issues": [objection()], "resolved_issue_ids": []},
    )
    first = run(
        benign,
        draft_of(benign),
        factory_for({"get_session_scores": ScriptedDriver([READ, escalate])}),
        session=session,
    )
    assert [(i.studentId, i.criterionId) for i in first.issues] == [("alex-tan", "reasoning")]
    assert session.pending is None  # no re-judge round is open
    audited = draft_of(benign, draft_of(benign), first)
    corrected = draft_of(benign, audited)
    second = run(
        benign,
        corrected,
        factory_for({"get_session_scores": ScriptedDriver([READ, finish()])}),
        session=session,
    )
    # The second case never received the objection, so its pass cannot resolve it: the issue
    # stays open for the professor (only a linked re-judge round resolves explicitly).
    app_id = "model:" + first.issues[0].id
    assert second.resolvedIssueIds == []
    assert "1 earlier Auditor issue(s) stay open" in second.notes
    final = draft_of(benign, corrected, second)
    assert next(i for i in final.audit.issues if i.id == app_id).disposition == "open"


def test_issue_overflow_is_surfaced_and_feedback_issues_are_kept(benign):
    from classpartai.participation.schema import ModelAudit, ModelAuditIssue

    many = [
        ModelAuditIssue(
            id=f"agent-{n}", studentId=None, criterionId=None, detail="Issue.", kind="support"
        )
        for n in range(100)  # a full agent result
    ]
    feedback = {
        "id": "alex-feedback",
        "studentId": "alex-tan",
        "criterionId": None,
        "detail": "Unsupported strength.",
        "kind": "feedback",
    }
    review = ScriptedDriver([("finish_feedback_audit", {**FEEDBACK_OK[1], "issues": [feedback]})])
    from classpartai.participation.auditor_bridge import _with_feedback_review

    merged = _with_feedback_review(
        ModelAudit(issues=many, resolvedIssueIds=[], resolutionReason="n/a", notes="Agent."),
        benign,
        draft_of(benign),
        [],
        budget(),
        factory_for({"finish_feedback_audit": review}),
    )
    assert len(merged.issues) == 100
    assert merged.issues[-1].id == "alex-feedback"
    overflow = merged.issues[-2]
    assert overflow.id.startswith("overflow-") and "2 further audit issue(s)" in overflow.detail


def test_a_timed_out_call_is_counted_before_the_coordinator_continues(inputs, monkeypatch):
    from classpartai.participation import auditor_bridge

    release = threading.Event()

    class HeldDriver(ScriptedDriver):
        def next(self, history):
            release.wait(5)
            turn = super().next(history)
            turn.tokens = 150
            return turn

    agent = HeldDriver([READ, finish()])
    real = auditor_bridge._limits

    def short(b):
        return real(b).__class__(model_calls=4, steps=4, seconds=0.05)

    monkeypatch.setattr(auditor_bridge, "_limits", short)
    threading.Timer(0.3, release.set).start()
    b = budget()
    no_feedback = compose_draft(
        Proposal(findings=Proposal.model_validate(full_proposal()).findings, feedback=[]),
        inputs,
        "test",
    )
    audit = run(inputs, no_feedback, factory_for({"get_session_scores": agent}), b)
    assert "budget_exhausted" in audit.notes
    # The held call finished and was counted before agent_audit returned control.
    assert (b.progress.modelCalls, b.progress.tokens) == (1, 150)
    time.sleep(0.2)
    assert (b.progress.modelCalls, b.progress.tokens) == (1, 150)  # nothing arrives later
