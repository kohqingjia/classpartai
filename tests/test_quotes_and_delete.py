"""Turn IDs shown as what the student said; deleting a session."""

import pytest
from conftest import full_proposal
from test_approval_delivery import REASON, FakeTransport, ready

from classpartai.participation.delivery import DeliverySettings, deliver_approved, feedback_email
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import Unprocessable
from classpartai.quotes import excerpt, quote_html, quote_plain

SAID = {"turn-1": "Chunking keeps ideas apart.", "turn-10": "It costs more <tokens> & $2."}


def test_a_turn_id_becomes_a_quote_of_what_was_said():
    assert quote_plain("In turn-1 you explained it.", SAID) == (
        "In “Chunking keeps ideas apart.” you explained it."
    )
    # the longer ID wins, and an ID inside another word or an unknown ID is left alone
    assert quote_plain("turn-10, not turn-100 or returnturn-1", SAID).startswith("“It costs")
    assert "turn-100" in quote_plain("turn-100", SAID)
    assert quote_plain("no ids", {}) == "no ids"


def test_quotes_on_screen_are_escaped_coloured_and_keep_the_id_on_hover():
    out = quote_html("<b>turn-10</b>", SAID)
    assert out.startswith("&lt;b&gt;<span style=")
    assert 'title="turn-10"' in out and "&lt;tokens&gt; &amp; &#36;2." in out


def test_a_long_turn_is_cut_at_a_word():
    cut = excerpt("word " * 60, limit=20)
    assert cut.endswith("…") and len(cut) <= 21 and "wor…" not in cut


def test_the_email_quotes_the_student_instead_of_naming_turn_ids(records, session_id):
    raw = full_proposal()
    raw["feedback"][0]["strengths"] = "In turn-002 you made the key point."
    draft = records.append_draft(session_id, Proposal.model_validate(raw), "model", "v")
    text = feedback_email(records, session_id, "alex-tan", draft)
    said = next(t.text for t in records.inputs(session_id).transcript.turns if t.id == "turn-002")
    assert "turn-002" not in text and f"“{excerpt(said)}”" in text


def test_deleting_a_session_removes_everything_made_from_it(records, session_id):
    draft = ready(records, session_id)
    records.approve_draft(session_id, draft.id, True, REASON, "prof")
    contents = records.session_contents(session_id)
    assert contents["draft versions"] == 1 and contents["approvals"] == 1
    assert contents["emails"] == 0
    records.delete_session(session_id)
    assert session_id not in {s["id"] for s in records.sessions()}
    assert records.db.execute("SELECT COUNT(*) FROM approvals").fetchone()[0] == 0
    with pytest.raises(Unprocessable, match="not found"):
        records.inputs(session_id)


def test_deleting_a_session_also_removes_its_lessons_and_summary(records, session_id):
    """Both tables were added after delete_session was written and were left behind."""
    records.note_lesson(session_id, "feedback", "writes-a-turn-id", "Quote the words instead.")
    records.save_summary(session_id, {"topics": ["chunking"]})
    records.delete_session(session_id)
    assert records.lessons(session_id) == []
    assert records.summary_for(session_id) is None


def test_a_session_whose_feedback_was_emailed_cannot_be_deleted(records, session_id):
    draft = ready(records, session_id)
    approval = records.approve_draft(session_id, draft.id, True, REASON, "prof")
    settings = DeliverySettings(test_mode=True, test_recipient="team@example.edu")
    deliver_approved(records, session_id, approval["id"], FakeTransport(), settings)
    with pytest.raises(Unprocessable, match="emailed"):
        records.delete_session(session_id)
    assert records.inputs(session_id)


def test_a_students_email_never_quotes_a_classmate(records, session_id):
    """Pullfrog #62: another student's turn ID in the free text stayed an ID, not their words."""
    raw = full_proposal()
    raw["feedback"][0]["strengths"] = "In turn-003 you made the key point."  # Priya's turn
    draft = records.append_draft(session_id, Proposal.model_validate(raw), "model", "v")
    text = feedback_email(records, session_id, "alex-tan", draft)
    priya = next(t.text for t in records.inputs(session_id).transcript.turns if t.id == "turn-003")
    # Not their words, and not a raw turn id either: the reader sees "another comment".
    assert excerpt(priya) not in text and "turn-003" not in text and "another comment" in text


def test_an_own_turn_that_names_a_classmate_is_shown_by_its_time(inputs):
    from classpartai.quotes import own_turns

    turn = next(t for t in inputs.transcript.turns if t.id == "turn-002")
    turn.text = "Building on what Priya\n  Nair said, retrieval happens at question time."
    shown = quote_plain("In turn-002 you did well.", own_turns(inputs, "alex-tan"))
    minutes, seconds = divmod(turn.startMs // 1000, 60)
    assert "Priya" not in shown and f"your comment at {minutes}:{seconds:02d}" in shown


def test_deletion_rechecks_for_sent_feedback_inside_its_transaction(
    records, session_id, monkeypatch
):
    """Pullfrog #62: a send that lands after the dialog's check still blocks the delete."""
    monkeypatch.setattr(records, "session_contents", lambda sid: {"emails": 0})
    draft = ready(records, session_id)
    approval = records.approve_draft(session_id, draft.id, True, REASON, "prof")
    settings = DeliverySettings(test_mode=True, test_recipient="team@example.edu")
    deliver_approved(records, session_id, approval["id"], FakeTransport(), settings)
    with pytest.raises(Unprocessable, match="emailed"):
        records.delete_session(session_id)
    assert records.latest_draft(session_id) is not None


def test_speaker_clips_are_removed_but_enrolments_are_kept(tmp_path):
    from classpartai.agents.listener import remove_speaker_clips

    (tmp_path / "speaker_00.wav").write_bytes(b"x")
    (tmp_path / "enrolled-tina.wav").write_bytes(b"x")
    remove_speaker_clips(tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["enrolled-tina.wav"]
