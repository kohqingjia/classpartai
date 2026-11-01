"""① Listener: turn a recording into a reviewed-transcript draft (owner: Tina, CPA-18/19/20).

Wraps audio-service/pipeline.py and maps its output onto the assessment transcript format.
Identified speakers become student turns; UNKNOWN / AMBIGUOUS become "uncertain" turns, which
can never establish a student's score. The professor confirms the transcript before it is used.
"""

import sys
from collections.abc import Callable

from classpartai.assessment import Transcript
from classpartai.config import AUDIO_SERVICE_DIR

IS_PLACEHOLDER = False


def load_pipeline() -> Callable[[str], dict]:
    # The pipeline loads its models at import time and needs HF_TOKEN, so import lazily.
    sys.path.insert(0, str(AUDIO_SERVICE_DIR))
    from pipeline import process_audio

    return process_audio


def to_transcript(result: dict, ids_by_name: dict[str, str], version: str) -> Transcript:
    """``ids_by_name`` maps a registered display name to its roster ID."""
    turns = []
    for n, seg in enumerate(result["segments"], start=1):
        start = int(seg["start"] * 1000)
        end = max(int(seg["end"] * 1000), start + 1)
        student_id = ids_by_name.get(seg["speaker"])
        if student_id:
            speaker = {"kind": "student", "studentId": student_id}
        else:
            label = "Ambiguous speaker" if seg["speaker"] == "AMBIGUOUS" else "Unknown speaker"
            speaker = {
                "kind": "uncertain",
                "label": label,
                "candidateStudentIds": [],
                "reason": "Voice did not match exactly one registered student",
            }
        turns.append(
            {
                "id": f"turn-{n:03d}",
                "startMs": start,
                "endMs": end,
                "speaker": speaker,
                "text": seg["text"] or "(inaudible)",
            }
        )
    return Transcript(version=version, reviewStatus="reviewed", turns=turns)
