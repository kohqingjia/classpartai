import pytest
from conftest import SILENT, ScriptedDriver, factory_for, feedback, full_proposal, judge_steps

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
            "score_contribution": ScriptedDriver(judge_steps()),
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
    first = {k: v for k, v in full_proposal()["findings"][0].items() if k != "studentId"}
    bad = {
        "students": [
            {"studentId": "alex-tan", "scores": [{**first, "score": 99, "confidence": "high"}]}
        ]
    }
    judge = ScriptedDriver([("score_contribution", bad)] * 9)  # the Judge gives up after 8 refusals
    roles = factory_for({"inspect_transcript_context": coordinator, "score_contribution": judge})
    coordinate(records, session_id, roles)
    actions = records.runs(session_id)[0]["progress"]["actions"]
    assert actions[0]["outcome"] == "invalid"
    assert records.latest_draft(session_id) is None
    # The Judge was told which rule it broke, then kept breaking it until it was stopped.
    assert "outside the pinned rubric range" in judge.histories[1][-1]["output"]


def test_judge_corrects_itself_after_rule_feedback(records, session_id):
    coordinator = ScriptedDriver([("propose_rubric_assessment", {"note": "First pass"})])
    coordinator.steps.append(("request_professor_review", {"summary": "stop"}))
    first = {k: v for k, v in full_proposal()["findings"][0].items() if k != "studentId"}
    wrong = {
        "students": [
            {
                "studentId": "alex-tan",
                "scores": [
                    {
                        **first,
                        "citations": [{"evidenceRunId": "review-1", "passageId": "turn-002"}],
                        "confidence": "high",
                    }
                ],
            }
        ]
    }
    judge = ScriptedDriver([("score_contribution", wrong), *judge_steps()])
    roles = factory_for({"inspect_transcript_context": coordinator, "score_contribution": judge})
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
    # 9 coordinator turns, 1 Judge call (it scores everyone at once), 4 feedback drafts, 1 audit.
    assert (p["modelCalls"], p["toolCalls"], p["tokens"]) == (15, 15, 150)
    assert p["elapsedSeconds"] >= 0
    calls = p["roleCalls"]
    assert len(calls) == 6
    judge = calls[0]
    assert judge["role"] == "judge_agent"
    assert judge["inputs"]["rubric"] == records.inputs(session_id).rubric.model_dump()
    assert judge["inputs"]["students"][0]["turns"]  # the students' own turns arrive up front
    assert judge["calls"][0]["name"] == "score_contribution"
    assert judge["output"]["complete"] is True
    assert judge["validation"] == "validate_proposal passed"
    assert all(c["outcome"] == "ok" for c in calls)
    assert p["actions"][0]["result"]["reviewedTurns"]
    assert "No provisional draft" in p["actions"][1]["result"]["error"]
    assert "untrustedData" in p["coordinatorInput"]["history"][0]["content"]


def test_trace_keeps_both_correction_attempts(records, session_id):
    test_judge_corrects_itself_after_rule_feedback(records, session_id)
    calls = records.runs(session_id)[0]["progress"]["roleCalls"]
    assert [c["outcome"] for c in calls[:2]] == ["refused", "ok"]
    assert "validated evidence" in calls[0]["reason"]
    assert len(calls[0]["history"]) == 1  # the opening message
    # Each later turn records only what is new: the previous tool's result.
    assert [i["type"] for i in calls[1]["history"]] == ["function_call_output"]


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
    coordinator = ScriptedDriver([("propose_rubric_assessment", {"note": "x"})])  # too short
    coordinate(records, session_id, factory_for({"inspect_transcript_context": coordinator}))
    action = records.runs(session_id)[0]["progress"]["actions"][0]
    assert action["outcome"] == "invalid"
    assert "Invalid arguments (note:" in action["summary"]
    assert "at least 3" in action["summary"]


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
            "score_contribution": ScriptedDriver(judge_steps()),
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


def test_a_rerun_scores_again_instead_of_reusing_the_last_runs_draft(records, session_id):
    """Run 7dd54fa5: on a session that already had scores, the Coordinator wrote feedback on
    the old draft and never called the Judge."""
    from classpartai.participation.schema import Proposal

    records.append_draft(session_id, Proposal.model_validate(full_proposal()), "model", "old")
    judge_driver = ScriptedDriver(judge_steps())
    coordinator = ScriptedDriver(
        [
            ("draft_student_feedback", {"studentId": "alex-tan"}),  # refused: not scored yet
            ("audit_assessment", {"note": "Audit the old draft"}),  # refused too
            ("propose_rubric_assessment", {"note": "Score this run"}),
        ]
    )
    roles = factory_for(
        {"inspect_transcript_context": coordinator, "score_contribution": judge_driver}
    )
    coordinate(records, session_id, roles)

    actions = records.runs(session_id)[0]["progress"]["actions"]
    assert [(a["tool"], a["outcome"]) for a in actions] == [
        ("draft_student_feedback", "invalid"),
        ("audit_assessment", "invalid"),
        ("propose_rubric_assessment", "ok"),
    ]
    assert "propose_rubric_assessment first" in actions[0]["result"]["error"]
    assert judge_driver.histories  # the Judge ran
    # A fresh score, not a revision of the old draft: the Judge saw no revision request
    assert "revision" not in judge_driver.histories[0][0]["content"]
    assert records.latest_draft(session_id).content.feedback == []


def test_an_overlong_note_is_shortened_not_refused():
    """Demo 1, run 9bf7cfac: refusing long notes made the model resend them until the budget
    ran out."""
    from classpartai.participation.coordinator import Review, Revise

    note = Revise.model_validate({"note": "x " * 900}).note
    assert len(note) == 1000 and note.endswith("…")
    assert len(Review.model_validate({"summary": "y" * 4000}).summary) == 1500
    assert Revise.model_validate({"note": "Short note"}).note == "Short note"


def test_the_coordinator_is_told_a_summary_not_the_whole_draft(records, session_id):
    """Demo 1, run c9964898: whole audits after every feedback draft filled the 100 KB history
    in 7 steps. Feedback results now say who still needs feedback, not every issue."""
    coordinator = ScriptedDriver(
        [
            ("propose_rubric_assessment", {"note": "First pass"}),
            ("draft_student_feedback", {"studentId": "alex-tan"}),
        ]
    )
    roles = factory_for(
        {
            "inspect_transcript_context": coordinator,
            "score_contribution": ScriptedDriver(judge_steps()),
            "finish_student_feedback": ScriptedDriver(
                [("finish_student_feedback", fb("alex-tan"))]
            ),
        }
    )
    coordinate(records, session_id, roles)
    proposed, drafted = records.runs(session_id)[0]["progress"]["actions"][:2]
    assert "justification" not in proposed["result"]["findings"][0]
    assert drafted["result"]["studentsWithoutFeedback"] == [
        "priya-nair",
        "jordan-wong",
        "marcus-lee",
    ]
    assert isinstance(drafted["result"]["openIssues"], int)
