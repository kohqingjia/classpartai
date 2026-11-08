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

        result.append(
            {
                "turn_id": turn.id,
                "speaker_id": speaker_id,
                "speaker_type": speaker.kind,
                "text": turn.text,
                "start_seconds": turn.startMs / 1000,
            }
        )

    return result


def get_participation_summary(transcript):
    """Count recorded student speaking turns."""
    counts = defaultdict(int)

    for turn in transcript.turns:
        if turn.speaker.kind == "student":
            counts[turn.speaker.studentId] += 1

    return dict(counts)
