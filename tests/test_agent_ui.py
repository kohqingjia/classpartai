"""Exercise real page navigation, persistence and read-only agent views without API calls."""

import json
import re

import pytest
import streamlit as st
from conftest import full_proposal
from streamlit.testing.v1 import AppTest

from classpartai import agent_ui, config
from classpartai.agent_ui import TABS
from classpartai.participation.records import Records
from classpartai.participation.schema import Proposal
from classpartai.ui import board_html, flow_html, vault_html
from classpartai.voices import match_rows


@pytest.fixture
def app(tmp_path, monkeypatch):
    st.cache_resource.clear()
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(agent_ui, "DATA_DIR", tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("EMAIL_TEST_MODE", "true")
    monkeypatch.setenv("EMAIL_TEST_RECIPIENT", "test@example.edu")
    at = AppTest.from_file(str(config.REPO_ROOT / "app.py"), default_timeout=20).run()
    yield at, Records(tmp_path / "assessments.db")
    st.cache_resource.clear()


def click(at, label):
    next(b for b in at.button if b.label == label).click().run()
    assert not at.exception


STEP_NUMBERS = {"Record": 1, "Who spoke?": 2, "AI assessment": 3, "Approve": 4, "Send": 5}


def navigate(at, step, agent=None):
    at.query_params.update(
        {"view": "session", "session": at.session_state["session_id"], "step": step}
    )
    if agent:
        at.session_state["agent"] = agent
        at.query_params["agent"] = agent
    at.run()
    assert not at.exception


def demo(at):
    click(at, "🎙️ New class session")
    click(at, "Skip to the demo transcript")
    return at.session_state["session_id"]


def test_every_outer_page_and_session_step(app):
    at, _ = app
    assert at.title[0].value == "ClassPart AI"
    for label, title in [
        ("📚 Course library", "Course library"),
        ("👥 Class & voices", "Class & voices"),
        ("🎙️ New class session", None),
    ]:
        click(at, label)
        if title:
            assert at.title[0].value == title
    # Steps 1-2 (Record, Who spoke?) are the New class session page; 3-5 are the session's.
    assert any("Record the seminar" in m.value for m in at.markdown)
    demo(at)
    for step in STEP_NUMBERS:
        navigate(at, step)
    click(at, "🏠 Home")
    assert at.title[0].value == "ClassPart AI"
    click(at, "🧭 How it works")
    assert at.title[0].value == "How ClassPart AI works"


def test_step_bar_names_the_agents_and_goes_back(app):
    at, _ = app
    demo(at)
    # A new session opens at its first open step, with every step clickable.
    assert next(b for b in at.button if b.key == "stepbar-3").proto.type == "primary"
    captions = " ".join(c.value for c in at.caption)
    for agent in ["Listener", "Coordinator", "Research", "Judge", "Auditor", "Feedback writer"]:
        assert agent in captions
    next(b for b in at.button if b.key == "stepbar-2").click().run()
    assert not at.exception
    assert at.query_params["step"] == "Who spoke?"
    assert any("Who spoke?" in m.value for m in at.markdown)
    click(at, "← Back to Record")
    assert at.query_params["step"] == "Record"
    click(at, "Next: ② Who spoke? →")
    click(at, "Next: ③ AI assessment →")
    assert at.query_params["step"] == "AI assessment"


def test_history_entries_always_name_their_step(app):
    """Browser Back restores an old address; it must show the step it showed before, even after
    the session has moved on (a pending transcript, a new draft)."""
    at, _ = app
    click(at, "🎙️ New class session")
    assert at.query_params["step"] == "Record"
    sid = demo(at)
    assert dict(at.query_params) == {
        "view": "session",
        "session": sid,
        "step": "AI assessment",
    }
    click(at, "🏠 Home")
    next(b for b in at.button if b.key == f"assessment-{sid}").click().run()
    assert at.query_params["step"] == "AI assessment"


@pytest.mark.parametrize("populated", [False, True])
def test_every_agent_tab_empty_and_populated(app, populated):
    at, records = app
    session_id = demo(at)
    if populated:
        records.append_draft(
            session_id, Proposal.model_validate(full_proposal()), "professor", "UI test fixture"
        )
    for agent in TABS:
        navigate(at, "AI assessment", agent)
        assert [t.label for t in at.tabs] == TABS
        if agent != "Overview":
            assert any(s.value == agent for s in at.subheader)
            # Presentation view avoids raw JSON, tool schemas and trace headings.
            assert not at.json
            assert not any("Tools it may call" in m.value for m in at.markdown)
            assert not at.toggle[0].value
            if populated and agent in agent_ui.ROLE_NAMES:
                assert any("professor draft" in m.value for m in at.markdown)
            at.toggle[0].set_value(True).run()
            assert not at.exception
            headings = [m.value for m in at.markdown]
            assert all(
                any(title in h for h in headings)
                for title in [
                    "Inputs",
                    "Tools it may call",
                    "Trajectory / timeline",
                    "Outputs",
                    "Guardrails that fired",
                ]
            )
    # Deep-linking a pipeline stage must work on a fresh browser session too.
    linked = AppTest.from_file(str(config.REPO_ROOT / "app.py"), default_timeout=20)
    linked.query_params.update({"session": session_id, "step": "AI assessment", "agent": "Judge"})
    linked.run()
    assert not linked.exception
    assert any(s.value == "Judge" for s in linked.subheader)


def test_approval_and_send_use_existing_gates(app, monkeypatch):
    from classpartai.participation import delivery

    class Transport:
        sent = []

        def __init__(self, *_):
            pass

        def send(self, to, subject, text, idempotency_key):
            self.sent.append(to)
            return "fake-accepted"

    monkeypatch.setattr(delivery, "AgentMailTransport", Transport)
    at, records = app
    session_id = demo(at)
    draft = records.append_draft(
        session_id, Proposal.model_validate(full_proposal()), "professor", "UI test fixture"
    )
    navigate(at, "Send")
    assert not any(b.label.startswith("Send 4 emails") for b in at.button)
    assert any("Approve a version" in i.value for i in at.info)
    navigate(at, "Approve")
    approve = next(b for b in at.button if b.label == f"Approve version {draft.version}")
    assert approve.disabled  # until the box is ticked and, with open issues, a reason given
    assert records.active_approval(session_id) is None
    at.checkbox[0].check()
    reason = next(t for t in at.text_input if t.label.startswith(("Why you're", "Note")))
    reason.input("Reviewed uncertainty and all evidence in this test fixture.")
    at.run()
    click(at, f"Approve version {draft.version}")
    assert records.active_approval(session_id)
    navigate(at, "Send")
    click(at, "Send 4 emails via AgentMail")
    assert Transport.sent == ["test@example.edu"] * 4
    click(at, "Send 4 emails via AgentMail")
    assert len(Transport.sent) == 4
    assert {d["state"] for d in records.deliveries(session_id)} == {"accepted"}


def test_iframe_text_cannot_escape_its_json_payload(inputs):
    attack = '</ScRiPt><img src=x onerror="alert(1)"> & <script>'
    documents = [d.model_dump() for d in inputs.documents]
    documents[0]["passages"][0]["text"] = attack
    pages = [
        flow_html(banner=attack, notes={"listener": attack}),
        board_html([(attack, "waiting", attack)]),
        vault_html(documents),
    ]
    for page in pages:
        assert attack not in page
        assert "innerHTML" not in page
        assert "textContent" in page
        payload = re.search(
            r'<script type="application/json" id="data">(.*?)</script>', page, re.S
        ).group(1)
        assert "<" not in payload
        assert attack in json.dumps(json.loads(payload), ensure_ascii=False).replace('\\"', '"')
    assert "requestAnimationFrame" not in pages[-1]
    assert "prefers-reduced-motion" in pages[-1]


def test_listener_diagnostics_preserve_scores_and_do_not_reassign(records, session_id):
    original = records.inputs(session_id).model_dump()
    diagnostics = {
        "aligned_segments": [
            {"start": 0, "end": 2, "text": "An uncertain line.", "speaker": "SPEAKER_00"}
        ],
        "voice_matches": {
            "SPEAKER_00": {
                "name": "AMBIGUOUS",
                "status": "ambiguous",
                "matches": [{"name": "Voice A", "score": 0.48}, {"name": "Voice B", "score": 0.44}],
            }
        },
    }
    records.save_listener_run(session_id, diagnostics)
    assert records.listener_run(session_id) == diagnostics
    row = match_rows(records.listener_run(session_id))[0]
    assert row["Identity"] == "AMBIGUOUS"
    assert row["Best cosine"] == 0.48
    assert row["Runner-up cosine"] == 0.44
    assert row["Margin"] == pytest.approx(0.04)
    assert records.inputs(session_id).model_dump() == original


def test_persisted_role_and_research_trajectories_render(app):
    from research.test_bridge import grader, request, scripted_agent
    from test_coordinator import test_coordinator_runs_the_whole_workflow

    from classpartai.research import bridge

    at, records = app
    session_id = demo(at)
    inputs = records.inputs(session_id)
    test_coordinator_runs_the_whole_workflow(records, session_id)
    question = request().model_copy(update={"sessionId": session_id})
    result = bridge.investigate(question, inputs, agent=scripted_agent(inputs, grader()))
    records.save_evidence_run(session_id, question.question, result)
    for agent in TABS[2:]:
        navigate(at, "AI assessment", agent)
        assert not at.exception
        at.toggle[0].set_value(True).run()
        assert not at.exception
    pack = result.progress.research[0]
    assert pack["model_history"][0]["role"] == "system"
    assert any(step["tool"] == "submit_findings" for step in pack["trajectory"])
    search = next(s for s in pack["trajectory"] if s["tool"] == "search_course_materials")
    assert "Course materials" in search["output"]
