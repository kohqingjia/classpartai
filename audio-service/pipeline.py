import json
import subprocess
import sys
from pathlib import Path
from diarization import diarize_audio
from alignment import align_speakers

BASE_DIR = Path(__file__).resolve().parent

from speaker_extraction import extract_speaker_audio
from speaker_identification import resolve_speaker_identity
from speaker_mapping import (
    replace_speaker_labels,
    merge_consecutive_speaker_segments,
)

BASE_DIR = Path(__file__).resolve().parent


def run_transcription(audio_path: str):
    result = subprocess.run(
        [
            sys.executable,
            str(BASE_DIR / "transcription_worker.py"),
            audio_path,
        ],
        capture_output=True,
        text=True,
        check=True,
    )

    return json.loads(result.stdout)

def process_audio(audio_path: str):

    # STEP 1 — Transcription
    print("Transcribing...")

    transcription = run_transcription(audio_path)


    # STEP 2 — Diarization
    print("Diarizing...")

    speaker_segments = diarize_audio(audio_path)


    # STEP 3 — Align transcript with diarized speakers
    print("Aligning transcript with speakers...")

    aligned_segments = align_speakers(
        transcription["segments"],
        speaker_segments,
    )


    # STEP 4 — Extract audio for each diarized speaker
    print("Extracting speaker audio...")

    speaker_files = extract_speaker_audio(
        audio_path,
        speaker_segments,
    )


    # STEP 5 — Identify each speaker using SpeechBrain
    print("Identifying speakers...")

    speaker_identities = {}

    for speaker_label, speaker_file in speaker_files.items():

        identity = resolve_speaker_identity(
            speaker_file
        )

        speaker_identities[speaker_label] = identity["name"]

        print(
            f"{speaker_label} -> "
            f"{identity['name']} "
            f"({identity['status']})"
        )


    # STEP 6 — Replace SPEAKER_XX with names
    identified_segments = replace_speaker_labels(
        aligned_segments,
        speaker_identities,
    )
    
    print("Merging consecutive speaker turns...")

    merged_segments = merge_consecutive_speaker_segments(
        identified_segments
    )


    return {
        "language": transcription["language"],
        "speaker_identities": speaker_identities,
        "segments": merged_segments,
    }   