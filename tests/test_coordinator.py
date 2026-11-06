from conftest import SILENT, ScriptedDriver, factory_for, feedback, full_proposal, judge_steps

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
