
from collections import defaultdict


def get_session_transcript(transcript):
    """Convert the reviewed transcript into agent-friendly data."""
    result = []

    for turn in transcript.turns:
        speaker = turn.speaker

        if speaker.kind == "student":
            speaker_id = speaker.studentId
        elif speaker.kind == "professor":
            speaker_id = "professor"
        else:
            speaker_id = "unknown"

        result.append({
            "turn_id": turn.id,
            "speaker_id": speaker_id,
            "speaker_type": speaker.kind,
            "text": turn.text,
            "start_seconds": turn.startMs / 1000,
        })

    return result


def get_participation_summary(transcript):
    """Count recorded student speaking turns."""
    counts = defaultdict(int)

    for turn in transcript.turns:
        if turn.speaker.kind == "student":
            counts[turn.speaker.studentId] += 1

    return dict(counts)


def get_existing_research(research_results, turn_id):
    """Retrieve existing evidence for a transcript turn."""
    return research_results.get(turn_id)


def investigate_contribution(
    research_agent,
    contribution,
    date,
    focus=None,
):
    """
    Ask the existing Research Agent to investigate
    a particular student contribution.
    """
    pack = research_agent.run(
        text=contribution["text"],
        date=date,
        question=contribution.get("question"),
        contribution_id=contribution.get("turn_id"),
        speaker=contribution.get("speaker_id"),
        focus=focus,
    )

    return {
        "contribution_id": pack.contribution_id,
        "claims": pack.claims,
        "correctness": pack.correctness,
        "mistake": pack.mistake,
        "summary": pack.summary,
        "needs_review": pack.needs_review,
        "stop_reason": pack.stop_reason,
        "usage": pack.usage,
    }
