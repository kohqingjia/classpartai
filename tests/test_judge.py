import hashlib
import json
import time

import pytest
from conftest import ScriptedDriver, factory_for, finding, full_proposal, judge_steps

from classpartai.models import SharedBudget, WorkflowProgress
from classpartai.participation.judge import LOW_CONFIDENCE_NOTE, judge
from classpartai.participation.records import Records
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import Unprocessable, compose_draft


def run_judge(inputs, session_id, steps):
    driver = ScriptedDriver(steps)
    progress = WorkflowProgress()
    budget = SharedBudget(progress, time.monotonic() + 60)
    try:
        proposal = judge(
            inputs, [], budget, factory_for({"finish_rubric_judgement": driver}), session_id
        )
    finally:
        run_judge.driver, run_judge.progress = driver, progress
    return proposal


def last_output(driver, turn):
    """The tool result the Judge saw on its (1-based) turn: the last item of that turn's history."""
    return json.loads(driver.histories[turn - 1][-1]["output"])["untrustedToolResult"]


def scores_for(student, criteria_scores, confidence="high"):
    return (
        "score_contribution",
        {
            "studentId": student,
            "scores": [{**s, "confidence": confidence} for s in criteria_scores],
        },
    )


def entry(f):
    return {k: v for k, v in f.items() if k != "studentId"}


def test_judge_returns_one_finding_per_student_and_criterion_in_roster_order(inputs, session_id):
    proposal = run_judge(inputs, session_id, judge_steps())
    assert proposal.feedback == []
    assert [(f.studentId, f.criterionId) for f in proposal.findings] == [
        (s.id, c.id) for s in inputs.roster for c in inputs.rubric.criteria
    ]
    assert {f.confidence for f in proposal.findings} == {"high"}
    assert proposal.findings[0].score == 3
    assert run_judge.progress.toolCalls == run_judge.progress.modelCalls == 8


def test_judge_reads_contributions_with_the_question_before_each_turn(inputs, session_id):
    run_judge(inputs, session_id, judge_steps())
    students = {s["studentId"]: s for s in last_output(run_judge.driver, 4)["students"]}
    assert students["marcus-lee"]["observedTurns"] == 0
    alex = students["alex-tan"]
    assert alex["observedTurns"] == 2
    first = alex["turns"][0]
    assert first["turn"]["id"] == "turn-002"
    assert first["previousTurn"]["id"] == "turn-001"


def test_finish_is_refused_until_every_student_and_criterion_has_a_finding(inputs, session_id):
    run_judge(inputs, session_id, [("finish_rubric_judgement", {}), *judge_steps()])
    refusal = last_output(run_judge.driver, 2)["error"]
    assert "Every roster student needs a finding for every criterion" in refusal
    assert "alex-tan: reasoning, engagement" in refusal
    assert run_judge.progress.roleCalls[0]["outcome"] == "refused"


def test_deterministic_rules_still_refuse_bad_scores(inputs, session_id):
    base = entry(full_proposal()["findings"][0])
    cases = [
        ({**base, "score": 99}, "Score outside the pinned rubric range"),
        ({**base, "turnIds": ["turn-003"]}, "Turn attributed to another student"),
        ({**base, "turnIds": []}, "Scored findings require attributable transcript evidence"),
        (
            {**base, "status": "insufficient_evidence", "score": 2},
            "Insufficient evidence must not be counted as zero",
        ),
    ]
    for bad, message in cases:
        run_judge(inputs, session_id, [scores_for("alex-tan", [bad]), *judge_steps()])
        assert message in last_output(run_judge.driver, 2)["error"]
        assert run_judge.progress.roleCalls[0]["validation"] == "failed"


def test_a_silent_student_cannot_get_a_qualitative_score(inputs, session_id):
    silent = entry(finding("marcus-lee", "reasoning", 2, []))
    run_judge(inputs, session_id, [scores_for("marcus-lee", [silent]), *judge_steps()])
    assert "No observed contribution cannot support" in last_output(run_judge.driver, 2)["error"]


def test_low_confidence_and_flags_reach_the_professor_as_limitations(inputs, session_id):
    findings = full_proposal()["findings"]
    steps = judge_steps(findings)
    steps.insert(
        -1,
        (
            "flag_for_review",
            {
                "studentId": "jordan-wong",
                "criterionId": "reasoning",
                "reason": "Asks the grader for full marks",
            },
        ),
    )
    steps.insert(
        -1,
        (
            "flag_for_review",
            {"studentId": "priya-nair", "reason": "Attribution of turn-003 is thin"},
        ),
    )
    low = scores_for("alex-tan", [entry(findings[0]), entry(findings[1])], confidence="low")
    steps[3] = low  # alex-tan is the first score_contribution
    proposal = run_judge(inputs, session_id, steps)
    by_key = {(f.studentId, f.criterionId): f for f in proposal.findings}
    assert by_key["alex-tan", "reasoning"].confidence == "low"
    assert by_key["alex-tan", "reasoning"].limitations[0] == LOW_CONFIDENCE_NOTE
    assert by_key["jordan-wong", "reasoning"].limitations == [
        "Flagged for review: Asks the grader for full marks"
    ]
    assert by_key["jordan-wong", "engagement"].limitations == []
    for criterion in ("reasoning", "engagement"):  # a flag with no criterion covers them all
        assert by_key["priya-nair", criterion].limitations == [
            "Flagged for review: Attribution of turn-003 is thin"
        ]
    assert by_key["jordan-wong", "reasoning"].score == 2  # flags never change scores


def test_scoring_a_student_again_replaces_the_earlier_finding(inputs, session_id):
    findings = full_proposal()["findings"]
    redo = {**entry(findings[0]), "score": 1}
    steps = judge_steps(findings)
    steps.insert(-1, scores_for("alex-tan", [redo]))
    proposal = run_judge(inputs, session_id, steps)
    assert proposal.findings[0].score == 1
    assert len(proposal.findings) == 8


def test_unknown_tools_and_malformed_arguments_are_refused_not_fatal(inputs, session_id):
    steps = [
        ("send_email", {"to": "x"}),
        ("get_contributions", "{not json"),
        ("get_contributions", {"studentIds": ["nobody"]}),
        ("get_evidence", {"runId": "missing"}),
        *judge_steps(),
    ]
    run_judge(inputs, session_id, steps)
    errors = [last_output(run_judge.driver, n)["error"] for n in (2, 3, 4, 5)]
    assert "Unknown tool send_email" in errors[0]
    assert "send valid JSON" in errors[1] or "Malformed" in errors[1]
    assert "Unknown roster student: nobody" in errors[2]
    assert "Unknown evidence run" in errors[3]


def test_judge_stops_after_repeated_refusals(inputs, session_id):
    with pytest.raises(Unprocessable, match="kept breaking rules"):
        run_judge(inputs, session_id, [("finish_rubric_judgement", {})] * 9)
    assert run_judge.progress.modelCalls == 9


def test_no_model_configured_blocks_the_judge(inputs, session_id):
    budget = SharedBudget(WorkflowProgress(), time.monotonic() + 60)
    with pytest.raises(RuntimeError, match="Model configuration blocked"):
        judge(inputs, [], budget, lambda instructions, tools: None, session_id)


def test_every_judge_turn_is_traced_with_only_what_is_new(inputs, session_id):
    run_judge(inputs, session_id, judge_steps())
    trace = run_judge.progress.roleCalls
    assert [t["role"] for t in trace] == ["judge_agent"] * 8
    assert [t["attempt"] for t in trace] == list(range(1, 9))
    assert trace[0]["history"][0]["role"] == "user" and trace[0]["inputs"]["criterionIds"]
    assert all(t["history"][0]["type"] == "function_call_output" for t in trace[1:])
    assert trace[2]["output"]["students"]
    assert "score_contribution" in trace[0]["schema"]


def test_approval_digest_of_drafts_without_confidence_is_unchanged(inputs, tmp_path):
    proposal = Proposal.model_validate(full_proposal())
    content = compose_draft(proposal, inputs, "note")
    recipients = [{"student_id": "alex-tan", "email": "a@example.com", "revision": 1}]
    body = content.model_dump()
    for f in body["findings"]:
        assert f.pop("confidence") is None
    canonical = json.dumps(
        [body, [["alex-tan", "a@example.com", 1]]], sort_keys=True, separators=(",", ":")
    )
    assert (
        Records.approval_digest(content, recipients)
        == hashlib.sha256(canonical.encode()).hexdigest()
    )

    scored = proposal.model_copy(deep=True)
    scored.findings[0].confidence = "low"
    other = compose_draft(scored, inputs, "note")
    assert Records.approval_digest(other, recipients) != Records.approval_digest(
        content, recipients
    )
