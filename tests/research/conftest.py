from pathlib import Path

import pytest

from classpartai.research.materials import load_materials, load_schedule
from classpartai.research.store import VectorStore

from .fakes import HashEmbedder

# A tiny invented course for the tests only, so they run in CI without the licensed IS469 files.
SAMPLE = Path(__file__).resolve().parent / "fixtures" / "mini_course"


@pytest.fixture(scope="session")
def schedule() -> dict:
    return load_schedule(SAMPLE)


@pytest.fixture(scope="session")
def store() -> VectorStore:
    return VectorStore.build(load_materials(SAMPLE), HashEmbedder())
