"""Shared settings: environment variables and the random seed every experiment uses."""

import os
import random

from dotenv import load_dotenv

load_dotenv()

SEED = int(os.getenv("SEED", "42"))

# Which models the agents use. "openai" (needs OPENAI_API_KEY) or "ollama" (free, runs locally;
# needs the Ollama app running with OLLAMA_MODEL and OLLAMA_EMBEDDING_MODEL pulled).
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai").strip().lower()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-5.4-mini")
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


def set_seed(seed: int = SEED) -> None:
    """Seed every random source in use so runs are reproducible.

    Add torch seeding here when that library joins the project.
    """
    import numpy as np

    random.seed(seed)
    np.random.seed(seed)
