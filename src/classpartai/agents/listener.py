"""① Listener: turn a recording into a reviewed-transcript draft (owner: Tina, CPA-18/19/20).

Wraps audio-service/pipeline.py and maps its output onto the assessment transcript format.
Identified speakers become student turns; UNKNOWN / AMBIGUOUS become "uncertain" turns, which
can never establish a student's score. The professor confirms the transcript before it is used.

If Tina's pipeline can't load (its pyannote diarization model is gated on Hugging Face, so a
token whose account hasn't accepted the model's terms gets a 403), the fallback skips
diarization: Whisper's segments are matched one by one against the enrolled voices with the
same SpeechBrain check. Short or unmatched segments stay uncertain.
"""

import json
import subprocess
import sys
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path

from classpartai.assessment import Transcript
from classpartai.config import AUDIO_SERVICE_DIR

IS_PLACEHOLDER = False
MIN_SEGMENT_SECONDS = 1.0  # shorter clips are too little voice to identify anyone
# Per-sentence matching (fallback only). Tina's rule ("more than one enrolled voice passes the
# verifier -> ambiguous") suits whole diarised speakers; single sentences pass for several
# voices, so here the best match must be good and clearly ahead of the runner-up.
MATCH_MIN_SCORE = 0.35
MATCH_MIN_MARGIN = 0.10


def best_match(matches: list[dict]) -> str:
    """A registered name, or UNKNOWN / AMBIGUOUS, from scored matches (best first)."""
    if not matches or matches[0]["score"] < MATCH_MIN_SCORE:
        return "UNKNOWN"
    runner_up = matches[1]["score"] if len(matches) > 1 else -1.0
    if matches[0]["score"] - runner_up < MATCH_MIN_MARGIN:
        return "AMBIGUOUS"
    return matches[0]["name"]


def load_pipeline() -> tuple[Callable[[str], dict], str | None]:
    """(process_audio, note): ``note`` explains when the fallback is in use."""
    # The pipeline loads its models at import time and needs HF_TOKEN, so import lazily.
    sys.path.insert(0, str(AUDIO_SERVICE_DIR))
    try:
        from pipeline import process_audio

        return process_audio, None
    except Exception as error:  # e.g. huggingface_hub GatedRepoError (403)
        reason = str(error).splitlines()[0][:200]
    import speaker_identification  # noqa: F401  (fails here if the voice model can't load)

    note = (
        "Speaker separation (pyannote) is unavailable, so each sentence's voice is matched "
        f"against the enrolled samples instead. Reason: {reason}"
    )
    return process_without_diarization, note


def process_without_diarization(audio_path: str) -> dict:
    """Tina's pipeline minus diarization: transcribe, then identify each segment's speaker.
    ``audio_path`` must be a WAV file (the app converts uploads to 16 kHz mono first)."""
    from speaker_identification import identify_speaker
    from speaker_mapping import merge_consecutive_speaker_segments

    worker = AUDIO_SERVICE_DIR / "transcription_worker.py"
    done = subprocess.run(
        [sys.executable, str(worker), audio_path], capture_output=True, text=True, check=True
    )
    transcription = json.loads(done.stdout)
    segments = []
    with tempfile.TemporaryDirectory() as tmp, wave.open(audio_path, "rb") as audio:
        rate = audio.getframerate()
        for n, seg in enumerate(transcription["segments"]):
            speaker = "UNKNOWN"
            identity = {"name": "UNKNOWN", "status": "too_short", "matches": []}
            if seg["end"] - seg["start"] >= MIN_SEGMENT_SECONDS:
                clip = Path(tmp) / f"segment-{n}.wav"
                audio.setpos(int(seg["start"] * rate))
                frames = audio.readframes(int((seg["end"] - seg["start"]) * rate))
                with wave.open(str(clip), "wb") as out:
                    out.setparams(audio.getparams())
                    out.writeframes(frames)
                matches = identify_speaker(str(clip))
                speaker = best_match(matches)
                scores = ", ".join(f"{m['name']} {m['score']:.2f}" for m in matches[:3])
                print(f"segment {n}: {speaker} ({scores})", flush=True)
                status = {"UNKNOWN": "unknown", "AMBIGUOUS": "ambiguous"}.get(speaker, "identified")
                identity = {"name": speaker, "status": status, "matches": matches}
            segments.append({**seg, "speaker": speaker, "voice_match": identity})
    return {
        "language": transcription["language"],
        "speaker_identities": {},
        # Diagnostics for the Listener inspector; not used by any model.
        "whisper_segments": transcription["segments"],
        "aligned_segments": segments,
        "matching": {"minScore": MATCH_MIN_SCORE, "minMargin": MATCH_MIN_MARGIN},
        "segments": merge_consecutive_speaker_segments(segments),
    }


def to_transcript(
    result: dict,
    ids_by_name: dict[str, str],
    version: str,
    professor_names: frozenset[str] | set[str] = frozenset(),
) -> Transcript:
    """``ids_by_name`` maps a registered student's display name to their roster ID;
    ``professor_names`` are registered professors' names, whose turns become professor turns."""
    turns = []
    for n, seg in enumerate(result["segments"], start=1):
        start = int(seg["start"] * 1000)
        end = max(int(seg["end"] * 1000), start + 1)
        student_id = ids_by_name.get(seg["speaker"])
        if seg["speaker"] in professor_names:
            speaker = {"kind": "professor", "label": seg["speaker"]}
        elif student_id:
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
