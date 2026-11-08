"""The Summary pipeline inside the app: the seminar briefing the professor reads at review.

Not an agent: ``analyse_session`` runs a fixed script of model calls (split the transcript,
analyse each part, consolidate, check which questions were answered later, drop references to
turns that do not exist). Code chooses every step. It runs once when the Coordinator hands the
session over for review, on the app's own model and usage ledger, and its failure never stops the
assessment: the briefing is simply missing.
"""

from __future__ import annotations

from classpartai import usage as ledger
from classpartai.assessment import AssessmentInputs
from classpartai.llm import ChatModel, OpenAIChat, extract_json
from classpartai.summary.agent import analyse_session


def generate_json(chat: ChatModel):
    def call(system_prompt: str, user_prompt: str) -> dict:
        reply = chat.complete(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            json_mode=True,
        )
        data = extract_json(reply.content)
        return data if isinstance(data, dict) else {}

    return call


@ledger.tracked("summary")
def summarise_seminar(inputs: AssessmentInputs, chat: ChatModel | None = None) -> dict:
    """{"analysis": {...topics, agreements, ...}, "participation": {student id: turns}}."""
    return analyse_session(inputs.transcript, generate_json(chat or OpenAIChat()))
