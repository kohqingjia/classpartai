import pytest
from conftest import full_proposal

from classpartai.participation.delivery import DeliverySettings, SendRejected, deliver_approved
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import Unprocessable

REASON = "Reviewed the uncertain turn and Marcus's missing evidence."


class FakeTransport:
    def __init__(self, fail=None):
        self.sent, self.fail = [], fail

    def send(self, to, subject, text, idempotency_key):
        if self.fail:
            raise self.fail
        self.sent.append({"to": to, "subject": subject, "text": text})
        return f"msg-{len(self.sent)}"


def ready(records, session_id):
    """A complete draft with every recipient set."""
    draft = records.append_draft(session_id, Proposal.model_validate(full_proposal()), "model", "v")
    for s in records.inputs(session_id).roster:
        records.set_recipient(session_id, s.id, f"{s.id}@example.edu")
    return draft


def test_drafts_are_versioned(records, session_id):
    first = records.create_professor_draft(session_id)
    second = records.append_draft(
        session_id, Proposal.model_validate(full_proposal()), "model", "judge", 1
    )
    assert (first.version, second.version) == (1, 2)
    with pytest.raises(Unprocessable, match="Draft changed"):
        records.append_draft(session_id, Proposal.model_validate(full_proposal()), "model", "x", 1)


def test_approval_needs_recipients_and_acknowledgement(records, session_id):
    draft = records.append_draft(session_id, Proposal.model_validate(full_proposal()), "model", "v")
    with pytest.raises(Unprocessable, match="recipient"):
        records.approve_draft(session_id, draft.id, True, REASON, "prof")
    for s in records.inputs(session_id).roster:
        records.set_recipient(session_id, s.id, f"{s.id}@example.edu")
    with pytest.raises(Unprocessable, match="acknowledgement"):
        records.approve_draft(session_id, draft.id, False, "", "prof")
    assert records.approve_draft(session_id, draft.id, True, REASON, "prof")["approver"] == "prof"


def test_blocking_issues_prevent_approval(records, session_id):
    raw = full_proposal()
    raw["feedback"] = raw["feedback"][:3]
    draft = records.append_draft(session_id, Proposal.model_validate(raw), "model", "v")
    with pytest.raises(Unprocessable, match="Complete every roster student"):
        records.approve_draft(session_id, draft.id, True, REASON, "prof")


def test_any_edit_invalidates_approval(records, session_id):
    draft = ready(records, session_id)
    records.approve_draft(session_id, draft.id, True, REASON, "prof")
    assert records.active_approval(session_id)
    records.set_recipient(session_id, "alex-tan", "alex.new@example.edu")
    assert records.active_approval(session_id) is None


def test_delivery_sends_once_per_student_and_test_mode_redirects(records, session_id):
    draft = ready(records, session_id)
    approval = records.approve_draft(session_id, draft.id, True, REASON, "prof")
    transport = FakeTransport()
    settings = DeliverySettings(test_mode=True, test_recipient="team@example.edu")
    results = deliver_approved(records, session_id, approval["id"], transport, settings)
    assert [r["state"] for r in results] == ["accepted"] * 4
    assert {m["to"] for m in transport.sent} == {"team@example.edu"}
    assert transport.sent[0]["subject"].startswith("[TEST → alex-tan@example.edu]")
    assert "Provisional participation score: 6/6" in transport.sent[0]["text"]
    assert "score" not in transport.sent[3]["text"].lower().split("next step")[0]
    again = deliver_approved(records, session_id, approval["id"], transport, settings)
    assert [r["state"] for r in again] == ["accepted"] * 4 and len(transport.sent) == 4


def test_rejected_can_retry_but_ambiguous_cannot(records, session_id):
    draft = ready(records, session_id)
    approval = records.approve_draft(session_id, draft.id, True, REASON, "prof")
    settings = DeliverySettings(test_mode=False)
    rejected = deliver_approved(
        records, session_id, approval["id"], FakeTransport(SendRejected("HTTP 400")), settings
    )
    assert {r["state"] for r in rejected} == {"rejected"}
    unknown = deliver_approved(
        records, session_id, approval["id"], FakeTransport(TimeoutError()), settings
    )
    assert {r["state"] for r in unknown} == {"ambiguous"}
    retry = FakeTransport()
    assert {
        r["state"] for r in deliver_approved(records, session_id, approval["id"], retry, settings)
    } == {"ambiguous"}
    assert retry.sent == []


def test_stale_approval_cannot_send(records, session_id):
    draft = ready(records, session_id)
    approval = records.approve_draft(session_id, draft.id, True, REASON, "prof")
    records.append_draft(session_id, Proposal.model_validate(full_proposal()), "professor", "edit")
    with pytest.raises(Unprocessable, match="Approval is missing"):
        deliver_approved(
            records, session_id, approval["id"], FakeTransport(), DeliverySettings(False)
        )
