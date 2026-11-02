"""Single-pass RAG: the fixed pipeline the agentic version is evaluated against.

One search of the course materials with the question and answer as said in class, one grading
call of the top k chunks against the answer, and no routing, query rewriting, retries, web, or
expected answer. It produces the same
EvidencePack as the agent, so the two can be scored by the same evaluation.
"""

from __future__ import annotations

import time

from classpartai.llm import ChatModel
from classpartai.research.agent import CountingChat, EvidencePack, correctness
from classpartai.research.store import VectorStore
from classpartai.research.tools import ResearchTools


def single_pass(
    text: str,
    date: str,
    llm: ChatModel,
    store: VectorStore,
    schedule: dict,
    *,
    question: str | None = None,
    k: int = 5,
    contribution_id: str | None = None,
) -> EvidencePack:
    started = time.perf_counter()
    counting = CountingChat(llm)
    tools = ResearchTools(store, schedule, counting)
    query = f"{question} {text}" if question else text
    tools.run("search_course_materials", {"query": query, "k": k}, step=1)
    ids = list(tools.evidence)
    if ids:
        tools.run("grade_evidence", {"claim": text, "chunks": ids}, step=1)
    return EvidencePack(
        text=text,
        date=date,
        kind="answer" if question else "contribution",
        contribution_id=contribution_id,
        question=question,
        lesson=None,
        route="course",
        route_reason="single-pass: always searches the course materials once",
        on_topic=None,
        on_topic_reason="",
        claims=(claims := tools.findings([text])),
        correctness=correctness(claims),
        reasoning=None,
        mistake=None,
        answers_question=None,
        expected_points=[],
        missed_points=[],
        summary="",
        needs_review=False,
        stop_reason="submitted",
        usage={
            "turns": 1,
            "course_searches": tools.course_searches,
            "web_searches": 0,
            "grade_calls": tools.grade_calls,
            "llm_calls": counting.calls,
            "seconds": round(time.perf_counter() - started, 2),
        },
        trajectory=[s.__dict__ for s in tools.trajectory],
    )
