from conftest import SILENT, ScriptedDriver, factory_for, feedback, full_proposal

from classpartai.participation.coordinator import coordinate

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
