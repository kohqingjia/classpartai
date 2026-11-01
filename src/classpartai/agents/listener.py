"""① Listener: turn a recording into contributions (owner: Tina, CPA-18/19/20).

Wraps audio-service/pipeline.py. That pipeline loads its models at import time and needs
HF_TOKEN, so it is imported only when a recording is actually processed.
"""

import sys
from collections.abc import Callable

from classpartai.config import AUDIO_SERVICE_DIR
from classpartai.contracts import Contribution

IS_PLACEHOLDER = False

# Turns shorter than this are treated as non-substantive ("can you repeat that?").
# TODO(Listener): replace with an LLM triage step (decision L2 in the README).
MIN_SUBSTANTIVE_WORDS = 6


def load_pipeline() -> Callable[[str], dict]:
    sys.path.insert(0, str(AUDIO_SERVICE_DIR))
    from pipeline import process_audio

    return process_audio


def to_contributions(
    result: dict, session_id: str, ids_by_name: dict[str, str]
) -> list[Contribution]:
    """Map the audio pipeline's output onto the shared Contribution contract.

    ``ids_by_name`` maps a registered display name to its class-list person_id.
    """
    contributions = []
    for n, seg in enumerate(result["segments"], start=1):
        speaker = seg["speaker"]
        person_id = ids_by_name.get(speaker)
        if person_id:
            status = "identified"
        elif speaker == "AMBIGUOUS":
            status = "ambiguous"
        else:
            status = "unknown"
        contributions.append(
            Contribution(
                id=f"{session_id}-c{n:03d}",
                session_id=session_id,
                person_id=person_id,
                speaker=speaker if person_id else status.upper(),
                speaker_status=status,
                start=seg["start"],
                end=seg["end"],
                text=seg["text"],
                substantive=len(seg["text"].split()) >= MIN_SUBSTANTIVE_WORDS,
            )
        )
    return contributions
