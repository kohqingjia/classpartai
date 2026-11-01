"""Send approved feedback (ported from participation/delivery.server.ts).

Unchanged rules: only with a current, un-invalidated approval whose digest matches the exact
draft and recipients; one delivery record per student per draft; a claim is recorded before
sending; accepted messages are never resent; a rejected send may be retried (max 3 attempts);
an ambiguous outcome is never retried automatically; at most 5 sends per click.

Changed: the original only allowed a local Mailpit capture server. This port sends through
AgentMail, and test mode (on by default) redirects every email to one inbox.
"""

import os
from dataclasses import dataclass
from typing import Protocol

from classpartai.participation.records import Records, new_id, now
from classpartai.participation.validation import Unprocessable, totals


class Transport(Protocol):
    def send(self, to: str, subject: str, text: str, idempotency_key: str) -> str:
        """Send one email; return the provider's message ID. Raise SendRejected if the
        provider definitely refused it; any other exception means the outcome is unknown."""
        ...


class SendRejected(Exception):
    pass


@dataclass
class DeliverySettings:
    test_mode: bool = True
    test_recipient: str = ""

    @classmethod
    def from_env(cls) -> "DeliverySettings":
        return cls(
            test_mode=os.getenv("EMAIL_TEST_MODE", "true").lower() != "false",
            test_recipient=os.getenv("EMAIL_TEST_RECIPIENT", ""),
        )


class AgentMailTransport:
    def __init__(self, api_key: str, inbox: str):
        from agentmail import AgentMail

        self.client = AgentMail(api_key=api_key)
        self.inbox = inbox

    def send(self, to: str, subject: str, text: str, idempotency_key: str) -> str:
        from agentmail.core.api_error import ApiError

        try:
            response = self.client.inboxes.messages.send(
                self.inbox,
                to=to,
                subject=subject,
                text=text,
                labels=["classpartai"],
                idempotency_key=idempotency_key,
            )
        except ApiError as error:
            if error.status_code and 400 <= error.status_code < 500:
                raise SendRejected(
                    f"AgentMail refused the message (HTTP {error.status_code})"
                ) from error
            raise
        return response.message_id


def feedback_email(records: Records, session_id: str, student_id: str, draft) -> str:
    inputs = records.inputs(session_id)
    feedback = next(f for f in draft.content.feedback if f.studentId == student_id)
    bundles = dict(records.evidence_for(session_id))
    references = []
    for c in feedback.citations:
        cite = next(
            (x for x in bundles[c.evidenceRunId].citations if x.passageId == c.passageId), None
        )
        if cite:
            references.append(f'- {cite.title}, p. {cite.page}: "{cite.excerpt}"')
    total = totals(draft.content, inputs, student_id)
    score = (
        f"Provisional participation score: {total['total']:g}/{total['maximum']}\n\n"
        if total["total"] is not None
        else ""
    )
    student = next(s for s in inputs.roster if s.id == student_id)
    return (
        f"Hi {student.displayName},\n\n"
        f"{feedback.strengths}\n\n"
        f"Next step: {feedback.nextStep}\n\n"
        f"{score}"
        + (f"Limitations: {'; '.join(feedback.limitations)}\n\n" if feedback.limitations else "")
        + ("Course references:\n" + "\n".join(references) + "\n\n" if references else "")
        + f"Professor-reviewed feedback for {inputs.sessionTitle}, version {draft.version}."
    )


def deliver_approved(
    records: Records,
    session_id: str,
    approval_id: str,
    transport: Transport,
    settings: DeliverySettings,
) -> list[dict]:
    inputs = records.inputs(session_id)
    records.review_state(session_id)
    if settings.test_mode and not settings.test_recipient:
        raise Unprocessable("Test mode is on but EMAIL_TEST_RECIPIENT is not set")
    results, attempted = [], 0
    for student in inputs.roster:
        if attempted >= 5:
            break
        with records.tx():
            draft = records.latest_draft(session_id)
            if draft is None:
                raise Unprocessable("No approved draft")
            approval = records._one(
                "SELECT * FROM approvals WHERE id = ? AND draft_id = ? AND invalidated_at IS NULL",
                (approval_id, draft.id),
            )
            recipients = records.recipients(session_id)
            if approval is None or approval["digest"] != records.approval_digest(
                draft.content, recipients
            ):
                raise Unprocessable(
                    "Approval is missing, invalidated or does not match the exact current "
                    "version and recipients"
                )
            recipient = next((r for r in recipients if r["student_id"] == student.id), None)
            if recipient is None:
                raise Unprocessable("Missing roster recipient")
            if not any(f.studentId == student.id for f in draft.content.feedback):
                raise Unprocessable("Missing approved individual feedback")
            previous = records._one(
                "SELECT * FROM deliveries WHERE draft_id = ? AND student_id = ?",
                (draft.id, student.id),
            )
            if previous and previous["state"] != "rejected":
                results.append({"studentId": student.id, "state": previous["state"]})
                continue
            attempt = (previous["attempts"] if previous else 0) + 1
            if attempt > 3:
                raise Unprocessable("Delivery retry limit reached; inspect the mail service")
            delivery_id = previous["id"] if previous else new_id()
            if previous:
                records.db.execute(
                    "UPDATE deliveries SET approval_id = ?, recipient = ?, state = 'sending',"
                    " attempts = ?, updated_at = ? WHERE id = ?",
                    (approval["id"], recipient["email"], attempt, now(), delivery_id),
                )
            else:
                records.db.execute(
                    "INSERT INTO deliveries VALUES (?, ?, ?, ?, ?, 'sending', ?, ?)",
                    (
                        delivery_id,
                        draft.id,
                        approval["id"],
                        student.id,
                        recipient["email"],
                        attempt,
                        now(),
                    ),
                )
            attempt_id = new_id()
            records.db.execute(
                "INSERT INTO delivery_attempts VALUES (?, ?, ?, 'sending', NULL, NULL, NULL, ?)",
                (attempt_id, delivery_id, attempt, now()),
            )
            text = feedback_email(records, session_id, student.id, draft)
        attempted += 1
        to, subject = recipient["email"], f"ClassPart AI feedback: {inputs.sessionTitle}"
        if settings.test_mode:
            to, subject = settings.test_recipient, f"[TEST → {recipient['email']}] {subject}"
        state, reason, message_id = "ambiguous", None, None
        try:
            message_id = transport.send(to, subject, text, f"classpart-{delivery_id}-{attempt}")
            state = "accepted"
        except SendRejected as error:
            state, reason = "rejected", f"{error}; explicit retry permitted"
        except Exception:
            reason = "Acceptance unknown; do not retry automatically"
        with records.tx():
            records.db.execute(
                "UPDATE deliveries SET state = ?, updated_at = ? WHERE id = ? AND state ="
                " 'sending'",
                (state, now(), delivery_id),
            )
            records.db.execute(
                "UPDATE delivery_attempts SET state = ?, reason = ?, message_id = ?, sent_to = ?"
                " WHERE id = ? AND state = 'sending'",
                (state, reason, message_id, to, attempt_id),
            )
        results.append({"studentId": student.id, "state": state})
    return results
