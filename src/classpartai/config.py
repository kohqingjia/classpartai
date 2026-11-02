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

# Which models the agents use. "openai" (needs OPENAI_API_KEY) or "ollama" (free, runs locally;
# needs the Ollama app running with OLLAMA_MODEL and OLLAMA_EMBEDDING_MODEL pulled).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5-mini")  # same default as models.py
OPENAI_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
# Optional thinking level for reasoning models ("none", "low", "medium", "high"); unset = default.
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT") or None

# Research agent. COURSE_DIR: the committed schedule and labelled contributions. MATERIALS_DIR:
# the lecture files (git-ignored, since they are licensed). INDEX_DIR: their embeddings.
COURSE_DIR = os.getenv("COURSE_DIR", "data/is469")
MATERIALS_DIR = os.getenv("MATERIALS_DIR", "data/raw/is469")
INDEX_DIR = os.getenv("INDEX_DIR", "data/index")
RESEARCH_MAX_STEPS = int(os.getenv("RESEARCH_MAX_STEPS", "12"))
RESEARCH_MAX_COURSE_SEARCHES = int(os.getenv("RESEARCH_MAX_COURSE_SEARCHES", "6"))
RESEARCH_MAX_WEB_SEARCHES = int(os.getenv("RESEARCH_MAX_WEB_SEARCHES", "3"))
RESEARCH_MAX_GRADES = int(os.getenv("RESEARCH_MAX_GRADES", "8"))

# Which agent answers the coordinator's retrieve_evidence: "research" (the Research agent through
# research/bridge.py, the default) or "course" (Le Yong's evidence agent in evidence.py). Inside a
# session, Research uses lighter budgets, since every call counts against the workflow's shared
# budget, and no web.
EVIDENCE_AGENT = os.getenv("EVIDENCE_AGENT", "research").strip().lower()
RESEARCH_BRIDGE_MAX_STEPS = int(os.getenv("RESEARCH_BRIDGE_MAX_STEPS", "8"))
RESEARCH_BRIDGE_MAX_COURSE_SEARCHES = int(os.getenv("RESEARCH_BRIDGE_MAX_COURSE_SEARCHES", "4"))
RESEARCH_BRIDGE_MAX_GRADES = int(os.getenv("RESEARCH_BRIDGE_MAX_GRADES", "5"))
# The documents a session made from a new recording searches. The default is the demo notes;
# point it at the file `python -m classpartai.research export-documents` writes to use the
# IS469 lecture files (licensed: keep it under var/, which git ignores).
COURSE_DOCUMENTS = Path(os.getenv("COURSE_DOCUMENTS", REPO_ROOT / "data" / "course_materials.json"))


def set_seed(seed: int = SEED) -> None:
    """Seed every random source in use so runs are reproducible.

    Add torch seeding here when that library joins the project.
    """
    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
