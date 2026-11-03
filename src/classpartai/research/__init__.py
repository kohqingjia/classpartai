"""② Research: agentic RAG that gathers evidence on each contribution for the Judge.

from classpartai.research import ResearchAgent

agent = ResearchAgent.from_config()
pack = agent.research_contribution({"id": "c7", "student": "S03", "text": "..."}, date="2026-09-01")
pack.claims, pack.brief()
"""

from classpartai.research.agent import EvidencePack, ResearchAgent
from classpartai.research.baseline import single_pass
from classpartai.research.materials import Chunk, lesson_for_date, load_materials, load_schedule
from classpartai.research.store import VectorStore

__all__ = [
    "Chunk",
    "EvidencePack",
    "ResearchAgent",
    "VectorStore",
    "lesson_for_date",
    "load_materials",
    "load_schedule",
    "single_pass",
]
