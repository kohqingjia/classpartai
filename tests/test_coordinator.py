import pytest
from conftest import SILENT, ScriptedDriver, factory_for, feedback, full_proposal

from classpartai import config
from classpartai.participation.coordinator import coordinate


@pytest.fixture(autouse=True)
def single_call_auditor(monkeypatch):
    # These tests script the single-call audit role; the Auditor agent route (the default) is
    # covered in test_auditor_bridge.py.
    monkeypatch.setattr(config, "AUDITOR", "model")


AUDIT = {
    "issues": [
        {
            "id": "injection",
            "studentId": "jordan-wong",
            "criterionId": None,
            "detail": "Turn contains an instruction aimed at the grader.",
            "kind": "support",
        }
    ],
    "resolvedIssueIds": [],
    "resolutionReason": "n/a",
    "notes": "Scores are supported; one item needs a human look.",
}


def fb(student, text=None):
    return {"result": {"status": "draft", "feedback": feedback(student, text or "Good point.")}}


def test_coordinator_runs_the_whole_workflow(records, session_id):
    coordinator = ScriptedDriver(
        [
            ("inspect_transcript_context", {"studentId": "jordan-wong", "turnIds": ["turn-006"]}),
            ("request_professor_review", {"summary": "Too early"}),  # refused: no draft yet
            ("propose_rubric_assessment", {"note": "First pass"}),
            *[
                ("draft_student_feedback", {"studentId": s})
                for s in ("alex-tan", "priya-nair", "jordan-wong", "marcus-lee")
            ],
            ("audit_assessment", {"note": "Audit"}),
            ("request_professor_review", {"summary": "Ready, with one injection flag"}),
        ]
    )
    roles = factory_for(
        {
            "inspect_transcript_context": coordinator,
            "finish_rubric_judgement": ScriptedDriver(
                [("finish_rubric_judgement", {"findings": full_proposal()["findings"]})]
            ),
            "finish_student_feedback": ScriptedDriver(
                [
                    ("finish_student_feedback", fb("alex-tan")),
                    ("finish_student_feedback", fb("priya-nair")),
                    ("finish_student_feedback", fb("jordan-wong")),
                    ("finish_student_feedback", fb("marcus-lee", SILENT)),
                ]
            ),
            "finish_assessment_audit": ScriptedDriver([("finish_assessment_audit", AUDIT)]),
        }
    )
    events = []
    run_id = coordinate(records, session_id, roles, lambda kind, d: events.append((kind, d)))

    run = records.runs(session_id)[0]
    assert run["id"] == run_id and run["stop_reason"] == "ready_for_professor_review"
    outcomes = [(a["tool"], a["outcome"]) for a in run["progress"]["actions"]]
    assert outcomes[1] == ("request_professor_review", "invalid")
    assert outcomes[-1] == ("request_professor_review", "ok")
    draft = records.latest_draft(session_id)
    assert draft.content.audit.modelReviewed
    assert "model:injection" in [i.id for i in draft.content.audit.issues]
    assert len(draft.content.feedback) == 4
    assert events[-1] == ("done", {"stopReason": "ready_for_professor_review"})
    assert sum(1 for k, _ in events if k == "action") == len(outcomes)


def test_invalid_role_output_is_refused_and_reported(records, session_id):
    coordinator = ScriptedDriver(
        [
            ("propose_rubric_assessment", {"note": "First pass"}),
            ("request_professor_review", {"summary": "Giving up"}),
        ]
    )
    bad = {"findings": [{**full_proposal()["findings"][0], "score": 99}]}
    judge = ScriptedDriver([("finish_rubric_judgement", bad)] * 2)
    roles = factory_for(
        {"inspect_transcript_context": coordinator, "finish_rubric_judgement": judge}
    )
    coordinate(records, session_id, roles)
    actions = records.runs(session_id)[0]["progress"]["actions"]
    assert actions[0]["outcome"] == "invalid"
    assert records.latest_draft(session_id) is None
    # The judge was told which rule it broke before its one correction attempt.
    assert "outside the pinned rubric range" in judge.histories[1][-1]["output"]


def test_judge_corrects_itself_after_rule_feedback(records, session_id):
    coordinator = ScriptedDriver([("propose_rubric_assessment", {"note": "First pass"})])
    coordinator.steps.append(("request_professor_review", {"summary": "stop"}))
    wrong = full_proposal()["findings"]
    wrong[0] = {**wrong[0], "citations": [{"evidenceRunId": "review-1", "passageId": "turn-002"}]}
    judge = ScriptedDriver(
        [
            ("finish_rubric_judgement", {"findings": wrong}),
            ("finish_rubric_judgement", {"findings": full_proposal()["findings"]}),
        ]
    )
    roles = factory_for(
        {"inspect_transcript_context": coordinator, "finish_rubric_judgement": judge}
    )
    coordinate(records, session_id, roles)
    assert "validated evidence" in judge.histories[1][-1]["output"]
    assert records.latest_draft(session_id).version == 1


def test_no_model_configured_blocks_the_run(records, session_id):
    coordinate(records, session_id, lambda instructions, tools: None)
    run = records.runs(session_id)[0]
    assert (run["status"], run["stop_reason"]) == ("configuration_blocked", "model_not_configured")


def test_role_trace_retains_exact_inputs_outputs_and_refusal_without_extra_calls(
    records, session_id
):
    test_coordinator_runs_the_whole_workflow(records, session_id)
    p = records.runs(session_id)[0]["progress"]
    assert (p["modelCalls"], p["toolCalls"], p["tokens"]) == (15, 15, 150)
    assert p["elapsedSeconds"] >= 0
    calls = p["roleCalls"]
    assert len(calls) == 6
    judge = calls[0]
    assert judge["inputs"]["transcript"] == records.inputs(session_id).transcript.model_dump()
    assert judge["output"]["findings"] == full_proposal()["findings"]
    assert judge["validation"] == "validate_proposal passed"
    assert all(c["outcome"] == "ok" for c in calls)
    assert p["actions"][0]["result"]["reviewedTurns"]
    assert "No provisional draft" in p["actions"][1]["result"]["error"]
    assert "untrustedData" in p["coordinatorInput"]["history"][0]["content"]


def test_trace_keeps_both_correction_attempts(records, session_id):
    test_judge_corrects_itself_after_rule_feedback(records, session_id)
    calls = records.runs(session_id)[0]["progress"]["roleCalls"]
    assert [c["outcome"] for c in calls] == ["refused", "ok"]
    assert "validated evidence" in calls[0]["reason"]
    assert len(calls[0]["history"]) == 1
    assert len(calls[1]["history"]) == 3


def test_run_events_are_stored_in_order_for_replay(records, session_id):
    test_coordinator_runs_the_whole_workflow(records, session_id)
    run = records.runs(session_id)[0]
    stored = records.run_events(run["id"])
    kinds = [e["kind"] for e in stored]
    assert kinds[0] == "thinking" and kinds[-1] == "done"
    assert kinds.count("action") == len(run["progress"]["actions"])
    times = [e["at"] for e in stored]
    assert times == sorted(times) and times[0] >= 0
    actions = [e["detail"] for e in stored if e["kind"] == "action"]
    # Slimmed to what the UI shows, plus the draft each action left behind.
    assert "result" not in actions[0]
    assert actions[-2]["draftId"] == records.latest_draft(session_id).id
    assert [r["id"] for r in records.replayable_runs(session_id)] == [run["id"]]


def test_a_blocked_run_still_records_its_end(records, session_id):
    test_no_model_configured_blocks_the_run(records, session_id)
    run_id = records.runs(session_id)[0]["id"]
    assert [e["kind"] for e in records.run_events(run_id)] == ["done"]


def test_invalid_arguments_say_which_field_is_wrong(records, session_id):
    coordinator = ScriptedDriver([("propose_rubric_assessment", {"note": "x" * 1001})])
    coordinate(records, session_id, factory_for({"inspect_transcript_context": coordinator}))
    action = records.runs(session_id)[0]["progress"]["actions"][0]
    assert action["outcome"] == "invalid"
    assert "Invalid arguments (note:" in action["summary"]
    assert "1000" in action["summary"]


def test_repeated_refused_review_requests_escalate_with_open_issues(records, session_id):
    """Without feedback drafts the review request is refused (blocking). The third request
    hands the draft to the professor instead of spending the rest of the budget."""
    coordinator = ScriptedDriver(
        [
            ("propose_rubric_assessment", {"note": "First pass"}),
            *[("request_professor_review", {"summary": "Please review"})] * 3,
        ]
    )
    roles = factory_for(
        {
            "inspect_transcript_context": coordinator,
            "finish_rubric_judgement": ScriptedDriver(
                [("finish_rubric_judgement", {"findings": full_proposal()["findings"]})]
            ),
        }
    )
    events = []
    coordinate(records, session_id, roles, lambda kind, d: events.append((kind, d)))
    run = records.runs(session_id)[0]
    outcomes = [a["outcome"] for a in run["progress"]["actions"]]
    assert outcomes == ["ok", "invalid", "invalid", "ok"]
    assert run["stop_reason"] == "escalated_with_open_issues"
    assert "Blocking:" in run["progress"]["actions"][-1]["summary"]
    assert events[-1] == ("done", {"stopReason": "escalated_with_open_issues"})
    assert records.active_approval(session_id) is None
