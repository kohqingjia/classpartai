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

1. Identify major discussion themes rather than every comment.

2. Group similar contributions under the same topic.

3. Identify agreement when multiple speakers express
   compatible viewpoints, even using different wording.

4. Identify disagreement when speakers express conflicting
   viewpoints about the same issue.

5. Only identify agreements and disagreements supported
   by actual transcript contributions.

6. For each finding, include relevant turn_ids.

7. Identify questions that appear unanswered within
   this transcript section.

8. Do not assume a question is unresolved for the entire
   seminar. It may be answered in a later section.

9. Identify factual claims that may require verification,
   but do not claim they have already been verified.

10. Do not invent discussions, speakers, or claims.

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
- Select 3 to 6 major themes when the content supports them.
- Merge repeated or closely related topics.
- Prioritise substantial, recurring, and relevant discussions.
- Provide a concise explanation for each theme.

AGREEMENTS:
- Identify compatible viewpoints from different speakers.
- Do not mistake one person's opinion for class consensus.
- Include supporting transcript turn IDs.
- Do not invent agreements.

DISAGREEMENTS:
- Identify contrasting positions on the same issue.
- Recognise implicit disagreement.
- Include supporting transcript turn IDs.
- Do not invent disagreements.

UNRESOLVED QUESTIONS:
- Review questions identified in earlier sections.
- Examine findings from later sections for possible answers.
- Remove questions that were adequately answered.
- Keep partially answered questions only if an important
  aspect remains unresolved.
- Do not invent questions that were never raised.
- Include the relevant turn IDs.

CLAIMS REQUIRING INVESTIGATION:
- Identify at most 2 important factual claims.
- Prioritise claims with uncertain or missing evidence.
- Reuse existing research findings where available.
- Do not describe a claim as verified unless supported
  by actual research evidence.
- Do not label claims as misconceptions yet.

SUGGESTED FOLLOW-UPS:
- Recommend practical actions for the professor.
- Base recommendations on discussion outcomes,
  unresolved questions, and evidence gaps.
- Avoid generic recommendations.

IMPORTANT:
- Only reference turn IDs supplied in the input.
- Be concise and evidence-grounded.
- Do not invent speakers, events, or findings.

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

For each question:

1. Identify where it was raised.
2. Examine later contributions for possible answers.
3. Determine whether it was adequately answered,
   partially answered, or left unanswered.
4. Exclude adequately answered questions.
5. Keep only genuinely unresolved or partially
   resolved questions.
6. Preserve supporting transcript turn IDs.
7. Do not invent answers or questions.

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
