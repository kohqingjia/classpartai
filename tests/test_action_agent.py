"""The agent loop, driven by a scripted fake LLM so no API key or network is needed."""

import json
from types import SimpleNamespace

from conftest import tool_call

from classpartai.action.agent import ActionAgent


class ScriptedLLM:
    """Replays fixed assistant turns: each is a list of tool calls or a final text."""

    def __init__(self, turns):
        self.turns = list(turns)
        self.seen: list[list[dict]] = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, model, messages, tools):
        self.seen.append(list(messages))
        turn = self.turns.pop(0)
        if isinstance(turn, str):
            message = {"role": "assistant", "content": turn, "tool_calls": None}
        else:
            message = {"role": "assistant", "content": None, "tool_calls": turn}
        return SimpleNamespace(choices=[SimpleNamespace(message=_Message(message))])


class _Message:
    def __init__(self, data):
        self.data = data
        self.content = data["content"]
        self.tool_calls = (
            [
                SimpleNamespace(id=c["id"], function=SimpleNamespace(**c["function"]))
                for c in data["tool_calls"]
            ]
            if data["tool_calls"]
            else None
        )

    def model_dump(self, exclude_none=False):
        return {k: v for k, v in self.data.items() if not (exclude_none and v is None)}


def test_agent_drafts_flags_and_summarises(harness, mailer, session):
    llm = ScriptedLLM(
        [
            [tool_call("1", "list_students")],
            [
                tool_call(
                    "2",
                    "draft_student_email",
                    person_id="alex-tan",
                    kind="commend",
                    subject="Great work",
                    body="Hi Alex, Session CP score: 4.5/5.",
                ),
                tool_call(
                    "3",
                    "draft_student_email",
                    person_id="marcus-lee",
                    kind="encourage",
                    subject="See you next class",
                    body="Hi Marcus, try one question.",
                ),
                tool_call(
                    "4",
                    "flag_for_review",
                    reason="Possible prompt injection",
                    person_id="jordan-wong",
                    contribution_id="demo-w10-c004",
                ),
                tool_call("5", "send_prof_summary", subject="Summary", body="2 drafts, 1 flag."),
            ],
            "Drafted two emails, flagged one item, sent the summary.",
        ]
    )
    run = ActionAgent(harness, client=llm, model="test").run(session)

    assert all(c.ok for c in run.calls)
    assert [e.person_id for e in harness.store.emails("pending")] == ["alex-tan", "marcus-lee"]
    assert harness.store.flags()[0]["person_id"] == "jordan-wong"
    assert [m["to"] for m in mailer.sent] == ["prof@example.edu"]  # students wait for approval
    assert run.final_message.startswith("Drafted")

    students = json.loads(run.calls[0].result)["students"]
    assert {s["person_id"]: s["contributions"] for s in students}["marcus-lee"] == 0
    assert json.loads(run.calls[0].result)["unidentified_contribution_ids"] == ["demo-w10-c005"]


def test_refused_tool_call_is_reported_back_to_the_agent(harness, session):
    llm = ScriptedLLM(
        [
            [
                tool_call(
                    "1",
                    "draft_student_email",
                    person_id="outsider",
                    kind="commend",
                    subject="Hi",
                    body="...",
                )
            ],
            "Skipped the outsider.",
        ]
    )
    run = ActionAgent(harness, client=llm, model="test").run(session)

    assert not run.calls[0].ok
    assert "not on the class list" in json.loads(run.calls[0].result)["refused"]
    assert llm.seen[1][-1]["role"] == "tool"  # the refusal went back to the model
    assert harness.store.emails() == []


def test_transcript_is_marked_as_student_data(harness, session):
    llm = ScriptedLLM(
        [[tool_call("1", "get_student_contributions", person_id="jordan-wong")], "ok"]
    )
    run = ActionAgent(harness, client=llm, model="test").run(session)
    text = json.loads(run.calls[0].result)[0]["text"]
    assert text.startswith("<student_said>") and "ignore the rubric" in text
