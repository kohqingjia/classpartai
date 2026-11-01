"""Shared settings: paths, environment variables and the random seed every experiment uses."""

import os
import random
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env")

SEED = int(os.getenv("SEED", "42"))

# Runtime state (class list, emails, audit log). A Docker volume on the VPS.
DATA_DIR = Path(os.getenv("CLASSPARTAI_DATA_DIR", REPO_ROOT / "var"))

# Voice samples live where audio-service/speaker_identification.py reads them.
AUDIO_SERVICE_DIR = REPO_ROOT / "audio-service"
ENROLLMENT_DIR = AUDIO_SERVICE_DIR / "enrollments"


def set_seed(seed: int = SEED) -> None:
    """Seed every random source in use so runs are reproducible.

    Add numpy/torch seeding here when those libraries join the project.
    """
    random.seed(seed)
