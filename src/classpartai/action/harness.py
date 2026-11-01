"""The Action harness: every rule about who may be emailed, enforced in code.

The Action agent proposes (drafts, flags, a summary); the harness decides what actually goes
out. Nothing here trusts the LLM: each rule holds whatever the agent asks for.

Rules
1. A student email is only sent after a person approves it in the webapp.
2. Recipients must be on the class list; the agent can't supply an address.
3. Unidentified speakers (no person_id) can never be emailed.
4. A student's email may not name any other student on the class list.
5. At most one email per student, kind and session (and an idempotency key per send).
6. A daily send cap, kept under AgentMail's limit.
7. Test mode (on by default) redirects every email to one test inbox.
"""

import os
import re
from dataclasses import dataclass

from classpartai.action.mailer import Mailer
from classpartai.action.store import Email, Store, now
from classpartai.classlist import ClassList

STUDENT_KINDS = {"commend", "encourage"}


class GuardrailError(Exception):
    """An action the harness refuses. The message is shown to the agent, so keep it actionable."""


@dataclass
class Settings:
    test_mode: bool = True
    test_recipient: str = ""
    prof_email: str = ""
    daily_cap: int = 50

    @classmethod
    def from_env(cls) -> "Settings":
        test_recipient = os.getenv("EMAIL_TEST_RECIPIENT", "")
        return cls(
            test_mode=os.getenv("EMAIL_TEST_MODE", "true").lower() != "false",
            test_recipient=test_recipient,
            prof_email=os.getenv("PROF_EMAIL", test_recipient),
            daily_cap=int(os.getenv("EMAIL_DAILY_CAP", "50")),
        )


class Harness:
    def __init__(self, store: Store, classlist: ClassList, mailer: Mailer, settings: Settings):
        self.store = store
        self.classlist = classlist
        self.mailer = mailer
        self.settings = settings

    # --- What the agent may do -------------------------------------------------------------

    def draft_student_email(
        self, session_id: str, person_id: str | None, kind: str, subject: str, body: str
    ) -> Email:
        if kind not in STUDENT_KINDS:
            raise GuardrailError(f"kind must be one of {sorted(STUDENT_KINDS)}")
        if not person_id:
            raise GuardrailError("Unidentified speakers can't be emailed; flag them for review.")
        student = self.classlist.get(person_id)
        if student is None:
            raise GuardrailError(f"{person_id!r} is not on the class list.")
        self._check_privacy(person_id, subject + "\n" + body)
        if self.store.find_email(session_id, person_id, kind):
            raise GuardrailError(f"A {kind} email for {person_id} already exists this session.")
        email = self.store.add_email(
            session_id=session_id,
            person_id=person_id,
            recipient=student.email,
            kind=kind,
            subject=subject,
            body=body,
            status="pending",
        )
        self.store.log("drafted", email_id=email.id, person_id=person_id, kind=kind)
        return email

    def flag_for_review(
        self, session_id: str, reason: str, person_id: str | None, contribution_id: str | None
    ) -> None:
        self.store.add_flag(session_id, person_id, contribution_id, reason)
        self.store.log("flagged", person_id=person_id, contribution_id=contribution_id)

    def send_prof_summary(self, session_id: str, subject: str, body: str) -> Email:
        """The prof's own summary is the one email that goes out without a separate approval."""
        if not self.settings.prof_email:
            raise GuardrailError("No PROF_EMAIL configured.")
        if self.store.find_email(session_id, None, "prof_summary"):
            raise GuardrailError("The prof summary for this session was already sent.")
        email = self.store.add_email(
            session_id=session_id,
            person_id=None,
            recipient=self.settings.prof_email,
            kind="prof_summary",
            subject=subject,
            body=body,
            status="approved",
        )
        return self._send(email, approver="system")

    # --- What a person does in the webapp ------------------------------------------------------

    def approve(
        self, email_id: int, approver: str, subject: str | None = None, body: str | None = None
    ) -> Email:
        email = self.store.get_email(email_id)
        if email.status != "pending":
            raise GuardrailError(f"Email {email_id} is {email.status}, not pending.")
        if subject is not None or body is not None:
            subject, body = subject or email.subject, body or email.body
            if email.person_id:
                self._check_privacy(email.person_id, subject + "\n" + body)
            email = self.store.update_email(email_id, subject=subject, body=body)
        email = self.store.update_email(email_id, status="approved")
        return self._send(email, approver=approver)

    def reject(self, email_id: int, approver: str) -> Email:
        email = self.store.get_email(email_id)
        if email.status != "pending":
            raise GuardrailError(f"Email {email_id} is {email.status}, not pending.")
        self.store.log("rejected", email_id=email_id, by=approver)
        return self.store.update_email(
            email_id, status="rejected", decided_by=approver, decided_at=now()
        )

    # --- Sending --------------------------------------------------------------------------------

    def _send(self, email: Email, approver: str) -> Email:
        if email.status != "approved":
            raise GuardrailError("Only approved emails can be sent.")
        if email.person_id:
            student = self.classlist.get(email.person_id)
            if student is None or student.email != email.recipient:
                raise GuardrailError("Recipient is no longer on the class list with that address.")
        if self.store.sent_today() >= self.settings.daily_cap:
            raise GuardrailError(f"Daily cap of {self.settings.daily_cap} emails reached.")

        to, subject = email.recipient, email.subject
        if self.settings.test_mode:
            to, subject = self.settings.test_recipient, f"[TEST → {email.recipient}] {subject}"
            if not to:
                raise GuardrailError("Test mode is on but EMAIL_TEST_RECIPIENT is empty.")

        try:
            message_id = self.mailer.send(to, subject, email.body, f"classpartai-email-{email.id}")
        except Exception as exc:  # delivery failure: record it, don't lose the draft
            self.store.log("send_failed", email_id=email.id, error=str(exc))
            return self.store.update_email(
                email.id, status="failed", error=str(exc), decided_by=approver, decided_at=now()
            )
        self.store.log("sent", email_id=email.id, to=to, by=approver, message_id=message_id)
        return self.store.update_email(
            email.id,
            status="sent",
            sent_to=to,
            message_id=message_id,
            decided_by=approver,
            decided_at=now(),
        )

    def _check_privacy(self, person_id: str, text: str) -> None:
        for other in self.classlist.all().values():
            if other.person_id == person_id:
                continue
            first = other.name.split()[0]
            if re.search(rf"\b{re.escape(first)}\b", text, re.IGNORECASE):
                raise GuardrailError(
                    f"The email mentions another student ({other.name}); "
                    "only refer to the recipient's own contributions."
                )
