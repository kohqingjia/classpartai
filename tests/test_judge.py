import hashlib
import json
import time

import pytest
from conftest import ScriptedDriver, factory_for, finding, full_proposal, judge_steps, score_call

from classpartai import usage
from classpartai.models import SharedBudget, WorkflowProgress
from classpartai.participation import judge as judge_module
from classpartai.participation.judge import (
    FLAG_PREFIX,
    LOW_CONFIDENCE_NOTE,
    Revision,
    judge,
    revision_targets,
)
from classpartai.participation.records import Records
from classpartai.participation.schema import AuditIssue, Finding, Proposal
from classpartai.participation.validation import Unprocessable, compose_draft


def run_judge(inputs, session_id, steps, revision=None):
    driver = ScriptedDriver(steps)
    progress = WorkflowProgress()
    budget = SharedBudget(progress, time.monotonic() + 60)
    try:
        proposal = judge(
            inputs,
            [],
            budget,
            factory_for({"score_contribution": driver}),
            session_id,
            revision,
        )
    finally:
        run_judge.driver, run_judge.progress = driver, progress
    return proposal


def opening(driver):
    """What the Judge was told in its first message."""
    return json.loads(driver.histories[0][0]["content"])["untrustedData"]


def last_output(driver, turn):
    """The tool result the Judge saw on its (1-based) turn: the last item of that turn's history."""
    return json.loads(driver.histories[turn - 1][-1]["output"])["untrustedToolResult"]


def entry(f, **extra):
    return {**{k: v for k, v in f.items() if k != "studentId"}, "confidence": "high", **extra}


def scores(student, *entries, **extra):
    return {"studentId": student, "scores": list(entries), **extra}


def call(*students):
    return ("score_contribution", {"students": list(students)})


# --- One call, no ceremony --------------------------------------------------------------------


def test_judge_scores_everyone_in_one_call_and_the_run_ends_by_itself(inputs, session_id):
    proposal = run_judge(inputs, session_id, judge_steps())
    assert proposal.feedback == []
    assert [(f.studentId, f.criterionId) for f in proposal.findings] == [
        (s.id, c.id) for s in inputs.roster for c in inputs.rubric.criteria
    ]
    assert {f.confidence for f in proposal.findings} == {"high"}
    assert proposal.findings[0].score == 3
    assert run_judge.progress.modelCalls == run_judge.progress.toolCalls == 1


def test_the_first_message_already_holds_the_rubric_turns_and_evidence_summary(inputs, session_id):
    run_judge(inputs, session_id, judge_steps())
    first = opening(run_judge.driver)
    assert first["rubric"] == inputs.rubric.model_dump()
    assert first["toScore"] == [s.id for s in inputs.roster]
    students = {s["studentId"]: s for s in first["students"]}
    assert students["marcus-lee"]["observedTurns"] == 0
    alex = students["alex-tan"]
    assert alex["observedTurns"] == 2
    assert alex["turns"][0]["turn"]["id"] == "turn-002"
    assert alex["turns"][0]["previousTurn"]["id"] == "turn-001"  # the question before it
    assert first["studentsWithoutTurnsHere_useGetContributions"] == []


def test_turns_that_do_not_fit_are_fetched_with_get_contributions(inputs, session_id, monkeypatch):
    monkeypatch.setattr(judge_module, "PRELOAD_BYTES", 1500)
    steps = [("get_contributions", {"studentIds": ["priya-nair"]}), *judge_steps()]
    run_judge(inputs, session_id, steps)
    left = opening(run_judge.driver)["studentsWithoutTurnsHere_useGetContributions"]
    assert "priya-nair" in left and len(left) < 4
    fetched = last_output(run_judge.driver, 2)["students"][0]
    assert fetched["studentId"] == "priya-nair" and fetched["turns"]


# --- Batching and refusals --------------------------------------------------------------------


def test_a_refused_student_does_not_stop_the_others_from_being_saved(inputs, session_id):
    findings = full_proposal()["findings"]
    by_student = {}
    for f in findings:
        by_student.setdefault(f["studentId"], []).append(f)
    bad = entry(by_student["jordan-wong"][0], score=99)
    students = [
        scores(s, *[entry(f) for f in fs]) for s, fs in by_student.items() if s != "jordan-wong"
    ]
    steps = [
        call(*students, scores("jordan-wong", bad, entry(by_student["jordan-wong"][1]))),
        call(scores("jordan-wong", *[entry(f) for f in by_student["jordan-wong"]])),
    ]
    proposal = run_judge(inputs, session_id, steps)
    first = last_output(run_judge.driver, 2)
    assert [r["studentId"] for r in first["refused"]] == ["jordan-wong"]
    assert "outside the pinned rubric range" in first["refused"][0]["reason"]
    assert first["studentsStillToScore"] == {"jordan-wong": ["reasoning", "engagement"]}
    assert run_judge.progress.modelCalls == 2  # only the refused student needed another call
    assert len(proposal.findings) == 8 and proposal.findings[4].score == 2


def test_deterministic_rules_still_refuse_bad_scores(inputs, session_id):
    base = full_proposal()["findings"][0]
    cases = [
        ({**entry(base), "score": 99}, "Score outside the pinned rubric range"),
        ({**entry(base), "turnIds": ["turn-003"]}, "Turn attributed to another student"),
        (
            {**entry(base), "turnIds": []},
            "Scored findings require attributable transcript evidence",
        ),
        (
            {**entry(base), "status": "insufficient_evidence", "score": 2},
            "Insufficient evidence must not be counted as zero",
        ),
    ]
    for bad, message in cases:
        run_judge(inputs, session_id, [call(scores("alex-tan", bad)), *judge_steps()])
        assert message in last_output(run_judge.driver, 2)["error"]
        assert run_judge.progress.roleCalls[0]["validation"] == "failed"


def test_a_silent_student_cannot_get_a_qualitative_score(inputs, session_id):
    silent = entry(finding("marcus-lee", "reasoning", 2, []))
    run_judge(inputs, session_id, [call(scores("marcus-lee", silent)), *judge_steps()])
    assert "No observed contribution cannot support" in last_output(run_judge.driver, 2)["error"]


def test_the_run_does_not_end_until_every_criterion_of_every_student_is_scored(inputs, session_id):
    findings = full_proposal()["findings"]
    partial = [
        f
        for f in findings
        if not (f["studentId"] == "alex-tan" and f["criterionId"] == "engagement")
    ]
    run_judge(inputs, session_id, [score_call(partial), score_call(findings)])
    assert last_output(run_judge.driver, 2)["studentsStillToScore"] == {"alex-tan": ["engagement"]}
    assert run_judge.progress.modelCalls == 2


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
        run_judge(inputs, session_id, [("send_email", {})] * 9)
    assert run_judge.progress.modelCalls == 9


def test_no_model_configured_blocks_the_judge(inputs, session_id):
    budget = SharedBudget(WorkflowProgress(), time.monotonic() + 60)
    with pytest.raises(RuntimeError, match="Model configuration blocked"):
        judge(inputs, [], budget, lambda instructions, tools: None, session_id)


# --- Confidence and flags ---------------------------------------------------------------------


def test_low_confidence_and_flags_reach_the_professor_as_limitations(inputs, session_id):
    findings = full_proposal()["findings"]
    by_student = {}
    for f in findings:
        by_student.setdefault(f["studentId"], []).append(f)
    students = [
        scores(
            "alex-tan",
            *[entry(f, confidence="low") for f in by_student["alex-tan"]],
        ),
        scores(
            "priya-nair",
            *[entry(f) for f in by_student["priya-nair"]],
            flag="Attribution of turn-003 is thin",
        ),
        scores(
            "jordan-wong",
            entry(by_student["jordan-wong"][0], flag="Asks the grader for full marks"),
            entry(by_student["jordan-wong"][1]),
        ),
        scores("marcus-lee", *[entry(f) for f in by_student["marcus-lee"]]),
    ]
    proposal = run_judge(inputs, session_id, [call(*students)])
    by_key = {(f.studentId, f.criterionId): f for f in proposal.findings}
    assert by_key["alex-tan", "reasoning"].confidence == "low"
    assert by_key["alex-tan", "reasoning"].limitations[0] == LOW_CONFIDENCE_NOTE
    assert by_key["jordan-wong", "reasoning"].limitations == [
        FLAG_PREFIX + "Asks the grader for full marks"
    ]
    assert by_key["jordan-wong", "engagement"].limitations == []
    for criterion in ("reasoning", "engagement"):  # a student-level flag covers every criterion
        assert by_key["priya-nair", criterion].limitations == [
            FLAG_PREFIX + "Attribution of turn-003 is thin"
        ]
    assert by_key["jordan-wong", "reasoning"].score == 2  # flags never change scores


def test_scoring_a_student_again_replaces_the_earlier_finding(inputs, session_id):
    findings = full_proposal()["findings"]
    redo = scores("alex-tan", entry({**findings[0], "score": 1}), entry(findings[1]))
    proposal = run_judge(inputs, session_id, [call(redo), *judge_steps()])
    assert run_judge.progress.modelCalls == 2
    assert proposal.findings[0].score == 3  # the second, complete call is the last word


# --- Revisions: re-score only who the audit objected to ---------------------------------------


def issue(id_, student, kind="support", disposition="open", criterion=None):
    return AuditIssue(
        id=id_,
        studentId=student,
        criterionId=criterion,
        kind=kind,
        detail="The justification does not match the turn.",
        severity="review",
        disposition=disposition,
        resolution=None,
    )


def previous():
    return [Finding.model_validate(f) for f in full_proposal()["findings"]]


def test_a_revision_rescores_only_the_students_the_audit_raised_issues_about(inputs, session_id):
    revision = Revision(
        "Audit says jordan is unsupported", previous(), [issue("model:a", "jordan-wong")]
    )
    assert revision_targets(revision, inputs) == ["jordan-wong"]
    jordan = [f for f in full_proposal()["findings"] if f["studentId"] == "jordan-wong"]
    fixed = [entry({**jordan[0], "score": 1}), entry(jordan[1])]
    proposal = run_judge(
        inputs, session_id, [call(scores("jordan-wong", *fixed))], revision=revision
    )
    first = opening(run_judge.driver)
    assert first["toScore"] == ["jordan-wong"]
    assert [s["studentId"] for s in first["students"]] == ["jordan-wong"]  # others need no turns
    assert first["revision"]["issues"][0]["id"] == "model:a"
    assert first["revision"]["previousFindings"][0]["studentId"] == "jordan-wong"
    assert run_judge.progress.modelCalls == 1  # not a full re-run
    by_key = {(f.studentId, f.criterionId): f for f in proposal.findings}
    assert by_key["jordan-wong", "reasoning"].score == 1  # revised
    assert by_key["alex-tan", "reasoning"].score == 3  # kept exactly as it was
    assert len(proposal.findings) == 8


def test_a_revision_without_a_specific_target_rescores_everyone(inputs):
    findings = previous()
    everyone = [s.id for s in inputs.roster]
    assert revision_targets(Revision("again", findings, []), inputs) == everyone
    assert (
        revision_targets(Revision("again", [], [issue("model:a", "jordan-wong")]), inputs)
        == everyone
    )
    assert (
        revision_targets(Revision("again", findings, [issue("model:a", None)]), inputs) == everyone
    )
    resolved = issue("model:a", "jordan-wong", disposition="revised")
    assert revision_targets(Revision("again", findings, [resolved]), inputs) == everyone
    other = [issue("model:a", "jordan-wong", kind="feedback"), issue("coverage:x", "alex-tan")]
    assert revision_targets(Revision("again", findings, other), inputs) == everyone


# --- Tracing ----------------------------------------------------------------------------------


def test_every_judge_turn_is_traced_with_only_what_is_new(inputs, session_id):
    run_judge(inputs, session_id, [("get_evidence", {"runId": "missing"}), *judge_steps()])
    trace = run_judge.progress.roleCalls
    assert [t["role"] for t in trace] == ["judge_agent"] * 2
    assert [t["outcome"] for t in trace] == ["refused", "ok"]
    assert trace[0]["history"][0]["role"] == "user" and trace[0]["inputs"]["rubric"]
    assert trace[1]["inputs"] is None and trace[1]["history"][0]["type"] == "function_call_output"
    assert trace[1]["output"]["complete"] is True
    assert "score_contribution" in trace[0]["schema"]


def test_judge_steps_are_reported_to_the_usage_ledger_under_the_judge(inputs, session_id):
    events = []
    with usage.tracking(sink=events.append, session_id=session_id):
        run_judge(inputs, session_id, [("get_evidence", {"runId": "missing"}), *judge_steps()])
    assert [(e["agent"], e["kind"], e["name"], e["status"]) for e in events] == [
        ("judge", "tool", "get_evidence", "refused"),
        ("judge", "tool", "score_contribution", "ok"),
    ]
    assert events[0]["detail"]["error"] and events[0]["session_id"] == session_id


# --- Approval digests -------------------------------------------------------------------------


def test_approval_digest_of_drafts_without_confidence_is_unchanged(inputs):
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
