import pytest

from classpartai.action.harness import GuardrailError

S = "demo-w10"


def draft(harness, person_id="alex-tan", kind="commend", body="Great point on query rewriting."):
    return harness.draft_student_email(S, person_id, kind, "Your CP feedback", body)


def test_draft_waits_for_approval(harness, mailer):
    email = draft(harness)
    assert email.status == "pending"
    assert email.recipient == "alex.tan@example.edu"
    assert mailer.sent == []


def test_approve_sends_once(harness, mailer):
    email = draft(harness)
    sent = harness.approve(email.id, "prof")
    assert sent.status == "sent" and sent.decided_by == "prof"
    assert [m["to"] for m in mailer.sent] == ["alex.tan@example.edu"]
    with pytest.raises(GuardrailError, match="not pending"):
        harness.approve(email.id, "prof")
    assert len(mailer.sent) == 1


def test_rejected_email_is_never_sent(harness, mailer):
    email = draft(harness)
    harness.reject(email.id, "prof")
    with pytest.raises(GuardrailError):
        harness.approve(email.id, "prof")
    assert mailer.sent == []


def test_recipient_must_be_on_class_list(harness):
    with pytest.raises(GuardrailError, match="not on the class list"):
        draft(harness, person_id="mallory")


def test_unidentified_speaker_cannot_be_emailed(harness):
    with pytest.raises(GuardrailError, match="Unidentified"):
        draft(harness, person_id=None)


def test_email_may_not_mention_another_student(harness):
    with pytest.raises(GuardrailError, match="Priya Nair"):
        draft(harness, body="You explained it better than Priya did.")


def test_privacy_rechecked_when_prof_edits(harness):
    email = draft(harness)
    with pytest.raises(GuardrailError, match="Jordan Wong"):
        harness.approve(email.id, "prof", body="Unlike Jordan, you stayed on topic.")


def test_one_email_per_student_kind_and_session(harness):
    draft(harness)
    with pytest.raises(GuardrailError, match="already exists"):
        draft(harness)


def test_test_mode_redirects_every_email(harness, mailer):
    harness.settings.test_mode = True
    harness.settings.test_recipient = "team@example.edu"
    sent = harness.approve(draft(harness).id, "prof")
    assert mailer.sent[0]["to"] == "team@example.edu"
    assert mailer.sent[0]["subject"].startswith("[TEST → alex.tan@example.edu]")
    assert sent.recipient == "alex.tan@example.edu" and sent.sent_to == "team@example.edu"


def test_daily_cap(harness, mailer):
    harness.settings.daily_cap = 1
    harness.approve(draft(harness).id, "prof")
    blocked = draft(harness, person_id="priya-nair", kind="encourage")
    with pytest.raises(GuardrailError, match="Daily cap"):
        harness.approve(blocked.id, "prof")
    assert len(mailer.sent) == 1


def test_delivery_failure_is_recorded(harness, mailer):
    mailer.fail = True
    sent = harness.approve(draft(harness).id, "prof")
    assert sent.status == "failed" and "provider down" in sent.error


def test_prof_summary_sends_without_approval_once(harness, mailer):
    assert harness.send_prof_summary(S, "Session summary", "4 students.").status == "sent"
    with pytest.raises(GuardrailError, match="already sent"):
        harness.send_prof_summary(S, "Again", "...")
    assert [m["to"] for m in mailer.sent] == ["prof@example.edu"]
