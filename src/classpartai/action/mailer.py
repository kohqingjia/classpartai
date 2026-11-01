"""Email delivery. The harness only ever sends through a Mailer, so tests can swap in a fake."""

from typing import Protocol


class Mailer(Protocol):
    def send(self, to: str, subject: str, text: str, idempotency_key: str) -> str:
        """Send one email and return the provider's message ID."""
        ...


class AgentMailMailer:
    def __init__(self, api_key: str, inbox: str):
        from agentmail import AgentMail

        self.client = AgentMail(api_key=api_key)
        self.inbox = inbox

    def send(self, to: str, subject: str, text: str, idempotency_key: str) -> str:
        response = self.client.inboxes.messages.send(
            self.inbox,
            to=to,
            subject=subject,
            text=text,
            labels=["classpartai"],
            idempotency_key=idempotency_key,
        )
        return response.message_id
