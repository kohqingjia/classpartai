import os
from pathlib import Path

import torch
from dotenv import load_dotenv
from pyannote.audio import Pipeline

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(ENV_PATH)

HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN environment variable is not set.")


pipeline = Pipeline.from_pretrained(
    "pyannote/speaker-diarization-community-1",
    token=HF_TOKEN,
)


def get_device():
    if torch.cuda.is_available():
        return torch.device("cuda")

    if torch.backends.mps.is_available():
        return torch.device("mps")

    return torch.device("cpu")


device = get_device()

print(f"Diarization device: {device}")

pipeline.to(device)


def diarize_audio(audio_path: str):
    output = pipeline(audio_path)

    speaker_segments = []

    for turn, speaker in output.speaker_diarization:
        if turn.end - turn.start < 0.3:
            continue

        speaker_segments.append(
            {
                "start": turn.start,
                "end": turn.end,
                "speaker": speaker,
            }
        )

    return speaker_segments
