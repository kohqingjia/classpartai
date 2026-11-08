from types import SimpleNamespace

import pytest
from conftest import SILENT, ScriptedDriver, factory_for, feedback, judge_steps

from classpartai import config, usage
from classpartai.llm import OpenAIChat, OpenAIEmbedder
from classpartai.models import ModelCall, OpenAIDriver, ToolDefinition
from classpartai.participation.coordinator import coordinate
from classpartai.participation.records import Records


@pytest.fixture(autouse=True)
def no_global_sink(monkeypatch):
    # Usage scripts explicitly target the single-call audit implementation.
    monkeypatch.setattr(config, "AUDITOR", "model")
    usage.configure(None)
    yield
    usage.configure(None)


def reply(prompt=1000, completion=200, cached=600, reasoning=150, calls=("score_contribution",)):
    """A chat-completions response, shaped like the OpenAI SDK's."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content="",
                    tool_calls=[
                        SimpleNamespace(
                            id=f"call-{n}", function=SimpleNamespace(name=name, arguments="{}")
                        )
                        for n, name in enumerate(calls)
                    ],
                )
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=prompt + completion,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
            completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning),
        ),
    )


class FakeClient:
    def __init__(self, response=None, error=None):
        self.requests = []
        self.response, self.error = response or reply(), error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))
        self.embeddings = SimpleNamespace(create=self.embed)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.error:
            raise self.error
        return self.response

    def embed(self, **kwargs):
        self.requests.append(kwargs)
        data = [SimpleNamespace(embedding=[1.0, 0.0]) for _ in kwargs["input"]]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=42, total_tokens=42))


def driver(client, provider="openai", model="gpt-5-mini"):
    return OpenAIDriver("be brief", [ToolDefinition("t", "d", {})], model, client, provider)


# --- Usage and cost ---------------------------------------------------------------------------


def test_usage_is_read_from_a_provider_response_and_missing_numbers_stay_none():
    assert usage.extract(reply().usage) == {
        "input": 1000,
        "output": 200,
        "cached": 600,
        "reasoning": 150,
    }
    assert usage.extract(None) == {"input": None, "output": None, "cached": None, "reasoning": None}


def test_cost_counts_cached_input_at_its_own_price_and_matches_dated_model_names():
    tokens = usage.extract(reply().usage)
    # 400 fresh input at 0.25, 600 cached at 0.025, 200 output at 2.00 (USD per million)
    expected = (400 * 0.25 + 600 * 0.025 + 200 * 2.0) / 1_000_000
    assert usage.cost_usd("gpt-5-mini", "openai", tokens) == pytest.approx(expected)
    assert usage.cost_usd("gpt-5-mini-2025-08-07", "openai", tokens) == pytest.approx(expected)


def test_a_model_without_a_price_has_no_cost_rather_than_zero():
    assert usage.cost_usd("some-new-model", "openai", usage.extract(reply().usage)) is None
    assert usage.cost_usd("gpt-5-mini", "openai", usage.extract(None)) is None


def test_local_models_cost_nothing():
    assert usage.cost_usd("qwen3:8b", "local", usage.extract(reply().usage)) == 0.0
    assert usage.cost_usd("qwen3:8b", "ollama", usage.extract(None)) == 0.0


# --- Context and sinks ------------------------------------------------------------------------


def test_events_carry_the_context_they_were_reported_in():
    events = []
    with usage.tracking(sink=events.append, run_id="r1", session_id="s1", agent="coordinator"):
        usage.record_step(usage.begin(), "inspect", "ok", {"arguments": "{}"})
        with usage.tracking(agent="judge"):
            usage.record_step(usage.begin(), "score", "refused", {"error": "x"})
        usage.update(run_id="r2")
        usage.record_step(usage.begin(), "again")
    assert [(e["agent"], e["run_id"], e["session_id"], e["name"]) for e in events] == [
        ("coordinator", "r1", "s1", "inspect"),
        ("judge", "r1", "s1", "score"),
        ("coordinator", "r2", "s1", "again"),
    ]
    assert events[1]["status"] == "refused" and events[0]["latency_ms"] >= 0


def test_the_agent_decorator_attributes_calls_and_then_restores_the_outer_agent():
    events = []

    @usage.tracked("research")
    def inner():
        usage.record_step(usage.begin(), "search")

    with usage.tracking(sink=events.append, agent="coordinator"):
        inner()
        usage.record_step(usage.begin(), "after")
    # The decorator also opens a span for the agent's work; the steps are the non-span events.
    assert [e["agent"] for e in events if e["kind"] != "span"] == ["research", "coordinator"]


def test_a_sink_that_fails_or_is_missing_never_breaks_the_run():
    usage.record_step(usage.begin(), "nobody listening")  # no sink at all

    def broken(event):
        raise RuntimeError("disk full")

    with usage.tracking(sink=broken):
        usage.record_step(usage.begin(), "still fine")


# --- The instrumented drivers -----------------------------------------------------------------


def test_the_driver_reports_tokens_model_latency_and_the_tools_the_model_asked_for():
    events = []
    client = FakeClient()
    with usage.tracking(sink=events.append, agent="feedback", run_id="r1"):
        turn = driver(client).next([{"role": "user", "content": "hi"}])
    assert turn.calls == [ModelCall("score_contribution", "call-0", "{}")] and turn.tokens == 1200
    (event,) = events
    assert (event["kind"], event["agent"], event["model"], event["status"]) == (
        "model",
        "feedback",
        "gpt-5-mini",
        "ok",
    )
    assert (event["input_tokens"], event["output_tokens"], event["cached_tokens"]) == (
        1000,
        200,
        600,
    )
    assert event["reasoning_tokens"] == 150
    assert event["detail"]["calls"] == ["score_contribution"]
    assert event["cost_usd"] == pytest.approx(0.000515)


def test_a_failed_call_is_recorded_with_its_reason_and_still_raises():
    events = []
    with usage.tracking(sink=events.append, agent="coordinator"):
        with pytest.raises(ValueError, match="invalid api key"):
            driver(FakeClient(error=ValueError("invalid api key"))).next([])
    assert events[0]["status"] == "error"
    assert "invalid api key" in events[0]["detail"]["error"] and events[0]["input_tokens"] is None


def test_reasoning_effort_is_set_per_agent_and_only_where_configured(monkeypatch):
    monkeypatch.setattr(config, "REASONING_EFFORT", {"judge": "low"})
    client = FakeClient()
    with usage.tracking(agent="judge"):
        driver(client).next([])
    with usage.tracking(agent="auditor"):
        driver(client).next([])
    driver(client).next([])
    assert [r.get("reasoning_effort") for r in client.requests] == ["low", None, None]
    monkeypatch.setattr(config, "REASONING_EFFORT", {})
    with usage.tracking(agent="judge"):
        driver(client).next([])
    assert "reasoning_effort" not in client.requests[-1]


def test_research_chat_calls_and_embeddings_are_recorded_too():
    events = []
    with usage.tracking(sink=events.append, agent="research"):
        OpenAIChat(model="gpt-5-mini", client=FakeClient(), provider="openai").complete([])
        OpenAIEmbedder(model="text-embedding-3-small", client=FakeClient()).encode(["a", "b"])
    assert [(e["kind"], e["model"]) for e in events] == [
        ("model", "gpt-5-mini"),
        ("embedding", "text-embedding-3-small"),
    ]
    assert events[1]["input_tokens"] == 42
    assert events[1]["cost_usd"] == pytest.approx(42 * 0.02 / 1_000_000)


# --- Storage ----------------------------------------------------------------------------------


def event(**over):
    base = {
        "id": over.get("id", "e1"),
        "ts": "2026-11-07T10:00:00.000+00:00",
        "run_id": None,
        "session_id": None,
        "agent": "judge",
        "kind": "model",
        "name": "gpt-5-mini",
        "provider": "openai",
        "model": "gpt-5-mini",
        "input_tokens": 100,
        "output_tokens": 50,
        "cached_tokens": 0,
        "reasoning_tokens": 10,
        "latency_ms": 800,
        "cost_usd": 0.001,
        "status": "ok",
        "detail": {"calls": ["x"]},
    }
    return {**base, **over}


def test_events_persist_across_restarts(tmp_path):
    path = tmp_path / "assessments.db"
    first = Records(path)
    first.log_event(event(id="a"))
    first.log_event(event(id="a"))  # the same event twice is stored once
    first.db.close()
    again = Records(path)
    (stored,) = again.events()
    assert (
        stored["id"] == "a" and stored["detail"] == {"calls": ["x"]} and stored["cost_usd"] == 0.001
    )


def test_events_come_back_in_the_order_they_started_and_filter_by_run_and_session(records):
    records.log_event(
        event(id="b", ts="2026-11-07T10:00:02.000+00:00", run_id="r1", session_id="s1")
    )
    records.log_event(
        event(id="a", ts="2026-11-07T10:00:01.000+00:00", run_id="r1", session_id="s1")
    )
    records.log_event(
        event(id="c", ts="2026-11-07T10:00:03.000+00:00", run_id="r2", session_id="s2")
    )
    assert [e["id"] for e in records.events(run_id="r1")] == ["a", "b"]
    assert [e["id"] for e in records.events(session_id="s2")] == ["c"]
    assert [e["id"] for e in records.events(limit=2)] == ["b", "c"]  # the latest two


def test_usage_rows_leave_out_trace_steps_and_respect_the_time_window(records):
    records.log_event(event(id="m"))
    records.log_event(event(id="t", kind="tool", name="score_contribution"))
    records.log_event(event(id="old", ts="2026-10-01T00:00:00.000+00:00"))
    assert [r["id"] for r in records.usage_rows()] == ["m", "old"] or {
        r["id"] for r in records.usage_rows()
    } == {"m", "old"}
    assert [r["id"] for r in records.usage_rows(since="2026-11-01")] == ["m"]


def test_summaries_group_calls_and_say_when_a_cost_is_only_a_lower_bound():
    rows = [
        event(id="1", agent="judge", latency_ms=100),
        event(id="2", agent="judge", latency_ms=300, cost_usd=None),
        event(id="3", agent="auditor", status="error", latency_ms=500, input_tokens=None),
        event(id="4", kind="tool", agent="judge"),
    ]
    by_agent = {g["group"]: g for g in usage.summarise(rows, "agent")}
    judge = by_agent["judge"]
    assert judge["calls"] == 2 and judge["input_tokens"] == 200 and judge["priced"] is False
    assert judge["avg_ms"] == 200 and judge["cost_usd"] == pytest.approx(0.001)
    assert by_agent["auditor"]["errors"] == 1 and by_agent["auditor"]["priced"] is True
    assert usage.summarise(rows)[0]["calls"] == 3  # tool steps are not model calls


# --- A whole workflow lands in the trace ------------------------------------------------------


def fb(student, text=None):
    return {"result": {"status": "draft", "feedback": feedback(student, text or "Good point.")}}


AUDIT = {
    "issues": [],
    "resolvedIssueIds": [],
    "resolutionReason": "n/a",
    "notes": "Scores are supported.",
}


def scripted_workflow(records, session_id, coordinator_steps=None):
    coordinator = ScriptedDriver(
        coordinator_steps
        or [
            ("propose_rubric_assessment", {"note": "First pass"}),
            *[
                ("draft_student_feedback", {"studentId": s})
                for s in ("alex-tan", "priya-nair", "jordan-wong", "marcus-lee")
            ],
            ("audit_assessment", {"note": "Audit"}),
            ("request_professor_review", {"summary": "Ready"}),
        ]
    )
    roles = factory_for(
        {
            "inspect_transcript_context": coordinator,
            "score_contribution": ScriptedDriver(judge_steps()),
            "finish_student_feedback": ScriptedDriver(
                [
                    ("finish_student_feedback", fb(s, SILENT if s == "marcus-lee" else None))
                    for s in ("alex-tan", "priya-nair", "jordan-wong", "marcus-lee")
                ]
            ),
            "finish_assessment_audit": ScriptedDriver([("finish_assessment_audit", AUDIT)]),
        }
    )
    return coordinate(records, session_id, roles)


def test_a_workflow_run_leaves_a_trace_of_every_step_under_its_run(records, session_id):
    run_id = scripted_workflow(records, session_id)
    trace = records.events(run_id=run_id)
    steps = [(e["agent"], e["name"], e["status"]) for e in trace if e["kind"] != "span"]
    # Ordered by when each started: the coordinator's step, then the Judge's inside it.
    assert steps[:2] == [
        ("coordinator", "propose_rubric_assessment", "ok"),
        ("judge", "score_contribution", "ok"),
    ]
    assert [n for a, n, _ in steps if a == "coordinator"] == [
        "propose_rubric_assessment",
        "draft_student_feedback",
        "draft_student_feedback",
        "draft_student_feedback",
        "draft_student_feedback",
        "audit_assessment",
        "request_professor_review",
    ]
    assert {e["session_id"] for e in trace} == {session_id}
    assert all(e["latency_ms"] is not None for e in trace)


def test_refused_actions_are_traced_with_their_reason(records, session_id):
    run_id = scripted_workflow(
        records,
        session_id,
        [
            ("request_professor_review", {"summary": "Too early"}),
            ("propose_rubric_assessment", {"note": "First pass"}),
            *[
                ("draft_student_feedback", {"studentId": s})
                for s in ("alex-tan", "priya-nair", "jordan-wong", "marcus-lee")
            ],
            ("audit_assessment", {"note": "Audit"}),
            ("request_professor_review", {"summary": "Ready"}),
        ],
    )
    refused = [e for e in records.events(run_id=run_id) if e["status"] == "refused"]
    assert [e["name"] for e in refused] == ["request_professor_review"]
    assert "No provisional draft" in refused[0]["detail"]["error"]


def test_the_runs_manifest_names_the_model(records, session_id):
    run_id = scripted_workflow(records, session_id)
    run = next(r for r in records.runs_with_usage() if r["id"] == run_id)
    assert run["manifest"]["model"] == config.OPENAI_MODEL
    assert run["manifest"]["reasoningEffort"] == config.REASONING_EFFORT
    assert run["title"] and run["calls"] == 0  # scripted drivers make no priced API calls


def test_a_run_that_fails_keeps_the_reason_the_run_record_drops(records, session_id):
    class Exploding:
        def estimate_tokens(self, history):
            return 10

        def next(self, history):
            raise ConnectionError("rate limited by the provider")

    run_id = coordinate(records, session_id, lambda instructions, tools: Exploding())
    run = records.runs(session_id)[0]
    assert run["stop_reason"] == "provider_failure"
    (error,) = [e for e in records.events(run_id=run_id) if e["kind"] == "error"]
    assert "rate limited by the provider" in error["detail"]["error"]


def test_calls_in_one_session_share_a_prompt_cache_key():
    client = FakeClient()
    driver(client).next([])  # no session running: no key
    with usage.tracking(session_id="s1", agent="judge"):
        driver(client).next([])
    assert "prompt_cache_key" not in client.requests[0]
    assert client.requests[1]["prompt_cache_key"] == "classpartai-s1"
