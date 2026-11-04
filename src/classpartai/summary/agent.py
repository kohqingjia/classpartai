
import json
from collections.abc import Callable

from classpartai.summary.prompts import SUMMARY_SYSTEM_PROMPT
from classpartai.summary.tools import (
    get_session_transcript,
    get_participation_summary,
)


def analyse_session(
    transcript,
    generate_json: Callable[[str, str], dict],
    existing_research=None,
):
    """
    Analyse a full session and propose investigations.

    generate_json(system_prompt, user_prompt)
    is supplied by the project's LLM adapter.
    """

    turns = get_session_transcript(transcript)
    participation = get_participation_summary(transcript)

    research = existing_research or {}

    payload = {
        "transcript": turns,
        "participation": participation,
        "existing_research": research,
    }

    user_prompt = f"""
Analyse this seminar:

{json.dumps(payload, ensure_ascii=False, default=str)}

Return a JSON object with these fields:

main_topics:
  list of objects with topic, explanation, turn_ids

agreements:
  list of objects with description, turn_ids

disagreements:
  list of objects with description, turn_ids

unresolved_questions:
  list of objects with question, turn_ids

investigations_needed:
  list of objects with turn_id, claim, reason

suggested_followups:
  list of strings

Select no more than two investigations.
Do not label claims as misconceptions yet.
"""

    analysis = generate_json(
        SUMMARY_SYSTEM_PROMPT,
        user_prompt,
    )

    if not isinstance(analysis, dict):
        raise ValueError("LLM must return a JSON object")

    analysis["investigations_needed"] = (
        analysis.get("investigations_needed") or []
    )[:2]

    return {
        "analysis": analysis,
        "participation": participation,
    }
