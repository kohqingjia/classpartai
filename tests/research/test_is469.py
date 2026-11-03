"""The IS469 setup: labs, a flat folder of lecture files, a deck shared by two weeks, and the
committed schedule and labelled contributions. Uses small generated files, since the real lecture
files are licensed and not in the repo."""

import json
from pathlib import Path

from classpartai.research.evaluate import load_labelled, score
from classpartai.research.materials import (
    lesson_for_date,
    load_materials,
    load_schedule,
    read_pages,
)
from classpartai.research.store import VectorStore
from classpartai.research.tools import ResearchTools

from .fakes import HashEmbedder, ScriptedLLM
from .test_evaluate import pack

IS469 = Path(__file__).resolve().parents[2] / "data" / "is469"


def notebook(path: Path, cells: list[tuple[str, str]]) -> None:
    path.write_text(
        json.dumps({"cells": [{"cell_type": t, "source": s, "outputs": []} for t, s in cells]})
    )


def test_notebook_cells_are_merged_and_numbered(tmp_path):
    path = tmp_path / "Topic7_Agentic_Lab.ipynb"
    notebook(
        path,
        [
            ("markdown", "# Stage 1"),
            ("code", ""),  # empty cells are skipped
            ("markdown", "The step budget is the stop condition. " * 10),
            ("code", "BUDGET = 6"),
        ],
    )
    pages = read_pages(path)
    assert pages[0][0] == 1 and "Stage 1" in pages[0][1] and "stop condition" in pages[0][1]
    assert pages[1] == (4, "BUDGET = 6")


def test_flat_folder_is_sorted_by_file_type_and_topic(tmp_path):
    from pptx import Presentation

    deck = Presentation()
    deck.slides.add_slide(
        deck.slide_layouts[1]
    ).shapes.title.text = "Temperature flattens the softmax"
    deck.save(tmp_path / "Topic5-6_Inference_Evaluation_IS469 (2).pptx")
    notebook(tmp_path / "Topic6_Evaluation_Lab.ipynb", [("markdown", "LLM-as-judge position bias")])
    schedule = load_schedule(IS469)

    chunks = load_materials(tmp_path, schedule)
    by_doc = {c.doc: c for c in chunks}
    deck_chunk = by_doc["Topic5-6_Inference_Evaluation_IS469 (2).pptx"]
    assert deck_chunk.kind == "slides" and deck_chunk.week == 5
    assert deck_chunk.source() == "Topic5 6 Inference Evaluation IS469 (slides), slide 1"
    lab = by_doc["Topic6_Evaluation_Lab.ipynb"]
    assert lab.kind == "lab" and lab.week == 6 and lab.source().endswith("(lab), cell 1")

    # A week 6 search also reaches the deck shared with week 5, through the schedule's patterns.
    store = VectorStore.build(chunks, HashEmbedder())
    tools = ResearchTools(store, schedule, ScriptedLLM())
    out = tools.run("search_course_materials", {"query": "temperature softmax", "week": 6}, 1)
    assert "Topic5 6 Inference Evaluation IS469 (slides), slide 1" in out
    assert {h.chunk.week for h in store.search("temperature", week=6)} == {6}  # without patterns


def test_is469_schedule_and_labelled_set_fit_together():
    schedule = load_schedule(IS469)
    assert [w["week"] for w in schedule["weeks"]] == list(range(1, 9))
    for item in load_labelled(IS469 / "eval_contributions.jsonl"):
        assert lesson_for_date(schedule, item["date"]) is not None, item["id"]
        assert set(item["expected_sources"]) <= {"none", "course", "web"}
        assert item["question"] and item["text"], item["id"]
        assert item["expected_answers_question"] in ("yes", "partly", "no"), item["id"]
        assert item.get("expected_reasoning") in (None, "explained", "asserted", "none")
        assert item.get("expected_mistake") in (
            None,
            "reasonable_guess",
            "misconception",
            "unsupported",
        )
        if item.get("expected_mistake"):
            assert item["expected_correctness"] in ("incorrect", "partially_correct")
        if item["expected_correctness"]:
            assert item["gold_docs"], item["id"]


def test_gold_patterns_match_file_names():
    item = {
        "id": "x",
        "expected_sources": ["course"],
        "expected_correctness": "correct",
        "gold_docs": ["*Topic5-6*", "*Topic6*"],
    }
    row = score(item, pack(docs=("Topic5-6_Inference_Evaluation_IS469 (2).pptx", "Topic2.ipynb")))
    assert row["context_precision"] == 0.5 and row["gold_hit"]
