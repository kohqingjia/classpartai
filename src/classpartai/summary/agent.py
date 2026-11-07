import json
from collections.abc import Callable

from classpartai.summary.prompts import SUMMARY_SYSTEM_PROMPT
from classpartai.summary.tools import (
    get_participation_summary,
    get_session_transcript,
)

# Approximate character-based chunking.
# Can be adjusted depending on your LLM's context window.
MAX_CHUNK_CHARS = 12000

SUMMARY_FIELDS = (
    "main_topics",
    "agreements",
    "disagreements",
    "unresolved_questions",
    "investigations_needed",
    "suggested_followups",
)


def _split_transcript(turns, max_chars=MAX_CHUNK_CHARS):
    """
    Split a long transcript into chunks without splitting
    individual speaking turns.
    """
    chunks = []
    current_chunk = []
    current_size = 0

    for turn in turns:
        turn_size = len(json.dumps(turn, ensure_ascii=False, default=str))

        if current_chunk and current_size + turn_size > max_chars:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0

        current_chunk.append(turn)
        current_size += turn_size

    if current_chunk:
        chunks.append(current_chunk)

    return chunks


def _call_llm(generate_json, prompt):
    """Call the LLM and validate its JSON response."""
    result = generate_json(SUMMARY_SYSTEM_PROMPT, prompt)

    if not isinstance(result, dict):
        raise ValueError("LLM must return a JSON object")

    return result


def _normalise_analysis(analysis):
    """Ensure all expected summary fields are lists."""
    normalised = {}

    for field in SUMMARY_FIELDS:
        value = analysis.get(field, [])
        normalised[field] = value if isinstance(value, list) else []

    normalised["main_topics"] = normalised["main_topics"][:6]
    normalised["investigations_needed"] = normalised["investigations_needed"][:2]

    return normalised


def _analyse_chunk(chunk, generate_json):
    """
    Analyse a section of the seminar transcript.
    This is an intermediate analysis, not the final summary.
    """
    prompt = f"""
Analyse this section of a university seminar transcript.

TRANSCRIPT:
{json.dumps(chunk, ensure_ascii=False, default=str)}

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


INSTRUCTIONS:

1. Identify only the major themes discussed in this chunk.
   Merge closely related concepts into broader topics.
   Use fewer topics when the discussion is short.

2. Preserve technical terms exactly as written in the
   transcript. Do not reinterpret LoRA as "Laura",
   QLoRA as "QL" or other invented abbreviations.

3. Identify agreements only when at least two different
   speakers express compatible positions on the same issue.
   Related explanations alone do not establish agreement.

4. Identify disagreements only when speakers express
   contrasting positions on the same issue.
   Distinguish professor corrections from student debates.

5. Only report questions that were explicitly asked.
   Check whether subsequent turns in this chunk answer them.

6. If a question appears unanswered in this chunk,
   treat it as a provisional candidate. It may be answered
   later in the seminar.

7. Do not turn interesting factual claims into questions.
   Put newly proposed questions under suggested_followups.

8. Identify important factual claims that may require
   verification, especially disputed or absolute claims.
   Do not claim they have already been researched.

9. Every agreement must cite turns from at least two
   different speakers. Every disagreement must cite
   the contrasting positions.

10. Return empty lists where there is insufficient
    transcript evidence. Do not invent findings.

Return valid JSON only.

"""
    return _call_llm(generate_json, prompt)


def _consolidate_analysis(
    turns,
    chunk_analyses,
    generate_json,
    existing_research,
):
    """
    Combine intermediate analyses into one seminar summary.

    The LLM must reconsider earlier unresolved questions
    against later discussion findings.
    """
    payload = {
        "chunk_analyses": chunk_analyses,
        "existing_research": existing_research,
        "transcript": turns,
        "transcript_turn_ids": [turn.get("turn_id") for turn in turns if isinstance(turn, dict)],
    }

    prompt = f"""
You are producing the FINAL professor briefing
for an entire university seminar.

The seminar has been analysed in chronological sections.

DATA:
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


MAIN DISCUSSION TOPICS:
- Select up to 5 major themes, fewer for short seminars.
- Merge related or overlapping topics.
- Prioritise concepts substantially discussed.
- Preserve the original technical terminology.
- Do not add uncertainty absent from the transcript.


AGREEMENTS:
- Identify agreement only when at least two distinct speakers
independently express the same or substantively compatible
position on a specific issue.
- For every agreement, identify at least two distinct speakers
and their supporting transcript turn IDs.
- Verify that each cited turn actually supports the agreement.
- Do not treat complementary explanations of different aspects
of a topic as agreement.
- Do not include statements made by only one speaker.
- Do not treat a professor's correction as class consensus
unless another participant supports the same position.
- Do not infer agreement merely because nobody objected.
- If an agreement cannot be supported by at least two
different speakers, exclude it.
- Return [] if no agreement meets these conditions.


DISAGREEMENTS:
- Require genuinely contrasting positions.
- Identify who expressed each position accurately.
- Distinguish student debates from professor corrections.
- Do not invent conflicts between compatible statements.

UNRESOLVED QUESTIONS:
- Only retain questions explicitly raised in the transcript.
- Check whether later turns answered each question.
- Exclude questions that were adequately answered.
- Exclude questions created by the AI during summarisation.
- Retain partially answered questions only if an important
  part of the original question remains unresolved.
- Return [] if no genuine unresolved questions remain.

CLAIMS REQUIRING INVESTIGATION:
- Select at most 2 important factual claims.
- Prioritise disputed, absolute or consequential claims.
- Use existing research findings when provided.
- Do not invent terminology uncertainty.
- Do not present unverified claims as proven false.

SUGGESTED FOLLOW-UPS:
- Recommend specific teaching or research actions.
- Focus on meaningful gaps or disputed claims.
- Do not repeat questions already answered in class.

IMPORTANT:
- Ground findings in actual transcript turns.
- Only use supplied turn IDs.
- Prefer accuracy over producing more findings.
- Empty lists are acceptable.
- Do not invent speakers, claims or questions.

Return valid JSON only.

"""
    return _call_llm(generate_json, prompt)


def _verify_unresolved_questions(
    turns,
    analysis,
    generate_json,
):
    """
    Re-check unresolved questions against the full transcript.

    This performs a second reasoning pass but does not
    guarantee that every question is classified correctly.
    """
    questions = analysis.get("unresolved_questions", [])

    if not questions:
        return analysis

    prompt = f"""
Review the following potentially unresolved seminar questions.

QUESTIONS:
{json.dumps(questions, ensure_ascii=False, default=str)}

FULL TRANSCRIPT:
{json.dumps(turns, ensure_ascii=False, default=str)}

For each candidate question, perform these checks:

CHECK 1: ORIGINAL QUESTION
- Find the exact transcript turn where the question
  was explicitly raised.
- If no such turn exists, remove the question.
- Do not treat an interesting topic or factual claim
  as an explicitly raised question.

CHECK 2: SUBSEQUENT ANSWERS
- Examine all later contributions in chronological order.
- Determine whether the original question was answered.
- Consider answers from students, guests and professors.

CHECK 3: RESOLUTION
- Fully answered: remove.
- Partially answered with no substantial gap: remove.
- Partially answered with an important remaining gap: keep.
- Not answered: keep.

CHECK 4: EVIDENCE
- Preserve the turn ID where the question was raised.
- Only include supporting turn IDs that exist in
  the transcript.
- Do not invent missing questions or answers.

CHECK 5: FINAL REVIEW
- Do not include new questions suggested by the AI.
- Do not include clarification questions about terminology
  already explicitly defined in the transcript.
- If no genuine unresolved questions remain, return [].

Return a JSON object with exactly this field:

unresolved_questions:
  list of objects with question, turn_ids

Return valid JSON only.

"""

    verification = _call_llm(generate_json, prompt)
    verified_questions = verification.get("unresolved_questions", [])

    if not isinstance(verified_questions, list):
        raise ValueError("unresolved_questions must be a list")

    analysis["unresolved_questions"] = verified_questions

    return analysis


def _filter_turn_ids(analysis, turns):
    """
    Remove invalid transcript references from findings.
    """
    valid_ids = {
        str(turn["turn_id"])
        for turn in turns
        if isinstance(turn, dict) and turn.get("turn_id") is not None
    }

    for field in (
        "main_topics",
        "agreements",
        "disagreements",
        "unresolved_questions",
    ):
        for item in analysis.get(field, []):
            if not isinstance(item, dict):
                continue

            ids = item.get("turn_ids", [])

            if not isinstance(ids, list):
                ids = []

            item["turn_ids"] = [turn_id for turn_id in ids if str(turn_id) in valid_ids]

    for item in analysis.get("investigations_needed", []):
        if not isinstance(item, dict):
            continue

        turn_id = item.get("turn_id")

        if turn_id is not None and str(turn_id) not in valid_ids:
            item["turn_id"] = None

    return analysis


def analyse_session(
    transcript,
    generate_json: Callable[[str, str], dict],
    existing_research=None,
):
    """
    Analyse an entire seminar and generate a structured
    professor briefing.

    Supports transcript chunking, theme consolidation,
    agreement/disagreement analysis, and a second pass
    for unresolved questions.

    generate_json(system_prompt, user_prompt)
    is supplied by the project's LLM adapter.
    """

    turns = get_session_transcript(transcript)
    participation = get_participation_summary(transcript)
    research = existing_research or {}

    if not turns:
        return {
            "analysis": {field: [] for field in SUMMARY_FIELDS},
            "participation": participation,
        }

    # Step 1: Split the transcript into manageable sections.
    chunks = _split_transcript(turns)

    # Step 2: Analyse each section independently.
    chunk_analyses = [_analyse_chunk(chunk, generate_json) for chunk in chunks]

    # Step 3: Consolidate the entire seminar.
    analysis = _consolidate_analysis(
        turns=turns,
        chunk_analyses=chunk_analyses,
        generate_json=generate_json,
        existing_research=research,
    )

    analysis = _normalise_analysis(analysis)

    # Step 4: Check whether questions were answered later.
    analysis = _verify_unresolved_questions(
        turns=turns,
        analysis=analysis,
        generate_json=generate_json,
    )

    # Step 5: Validate transcript references.
    analysis = _filter_turn_ids(analysis, turns)

    return {
        "analysis": analysis,
        "participation": participation,
    }
