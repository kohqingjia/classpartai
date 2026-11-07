"""The comparison runner (eval/research_eval.py) and its usage meter, offline."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from classpartai.llm import OpenAIChat, OpenAIEmbedder
from classpartai.research.agent import ResearchAgent
from classpartai.research.bridge import documents_from_materials
from classpartai.research.evaluate import SpendLimitReached, UsageMeter, compare, load_labelled

from .conftest import SAMPLE
from .fakes import (
    HashEmbedder,
    ScriptedLLM,
    call,
    ids_in,
    keyword_grader,
    last_tool_result,
    submit,
    turn,
)
from .test_evaluate import pack

_spec = importlib.util.spec_from_file_location(
    "research_eval", Path(__file__).resolve().parents[2] / "eval" / "research_eval.py"
)
research_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(research_eval)


class FakeOpenAI:
    """Answers chat and embedding calls with fixed usage, the way the OpenAI client reports it."""

    def __init__(self):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._chat))
        self.embeddings = SimpleNamespace(create=self._embed)

    def _chat(self, **kwargs):
        message = SimpleNamespace(content="ok", tool_calls=None)
        usage = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=500,
            total_tokens=1500,
            prompt_tokens_details=SimpleNamespace(cached_tokens=400),
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    def _embed(self, **kwargs):
        data = [SimpleNamespace(embedding=[1.0, 0.0]) for _ in kwargs["input"]]
        return SimpleNamespace(data=data, usage=SimpleNamespace(prompt_tokens=10))


def test_meter_counts_tokens_and_cost_by_model_and_enforces_the_budget():
    meter = UsageMeter(FakeOpenAI(), max_usd=0.002)
    chat = OpenAIChat(model="gpt-5-mini", client=meter, provider="openai")
    embedder = OpenAIEmbedder(model="text-embedding-3-small", client=meter, provider="openai")
    before = meter.snapshot()
    assert chat.complete([{"role": "user", "content": "hi"}]).tokens == 1500
    embedder.encode(["a", "b"])
    spent = meter.since(before)
    assert spent["gpt-5-mini"] == {"calls": 1, "input": 1000, "cached": 400, "output": 500}
    assert spent["text-embedding-3-small"]["input"] == 10
    # 600 fresh input at $0.25/M, 400 cached at $0.025/M, 500 output at $2/M, 10 embedded at $0.02/M
    assert meter.cost() == pytest.approx((600 * 0.25 + 400 * 0.025 + 500 * 2 + 10 * 0.02) / 1e6)
    chat.complete([{"role": "user", "content": "again"}])  # now over US$0.002
    with pytest.raises(SpendLimitReached, match="Budget spent"):
        chat.complete([{"role": "user", "content": "one too many"}])


def test_library_documents_are_indexed_like_a_session(tmp_path, schedule):
    documents = documents_from_materials(SAMPLE)
    library = [{"file": "x", "uploadedAt": "2026-11-01", "document": d} for d in documents]
    path = tmp_path / "documents.json"
    path.write_text(json.dumps(library))
    loaded = research_eval.load_documents(path)
    assert [d.id for d in loaded] == [d["id"] for d in documents]
    store = research_eval.build_store(loaded, HashEmbedder(), schedule, tmp_path / "cache")
    assert store.chunks and all("#" in c.id for c in store.chunks)
    assert (tmp_path / "cache").is_dir()  # cached by content, like the app's index


def test_comparison_writes_tables_and_per_item_results(tmp_path, store, schedule):
    items = [i for i in load_labelled(SAMPLE / "eval_contributions.jsonl") if i["id"] == "e01"]
    llm = ScriptedLLM(
        [turn(submit(route_reason="logistics question, no claim"))],
        grader=keyword_grader({"repeat": ("relevant", "supports")}),
    )
    agent = ResearchAgent(llm, store, schedule)
    meter = UsageMeter(FakeOpenAI())  # the scripted model never calls it: zero usage
    report = research_eval.run_comparison(items, agent, meter)
    report["config"] = {
        "model": llm.name,
        "embedder": "test:hash",
        "web": None,
        "items": "mini",
        "corpus": "mini course",
        "seed": 42,
        "run_at": "now",
    }
    path = research_eval.write_results(report, items, tmp_path, "run")

    saved = json.loads(path.with_suffix(".json").read_text())
    [agentic] = saved["agentic"]["rows"]
    assert agentic["route"] == "none" and agentic["routed_correctly"] is True
    assert saved["single_pass"]["rows"][0]["route"] == "course"  # single-pass always searches
    assert saved["agentic"]["usage"]["usd"] == 0 and agentic["tokens"] == 0
    table = path.with_suffix(".md").read_text()
    assert "| routed_correctly | n/a | 1.00 |" in table
    assert "| e01 |" in table


def test_saved_quotes_are_cut_short():
    from classpartai.research.evaluate import QUOTE_WORDS, _brief_claim

    long_quote = " ".join(f"w{i}" for i in range(60))
    claim = {
        "claim": "c",
        "status": "supported",
        "evidence": [{"doc": "d", "page": 1, "quote": long_quote, "text": long_quote}],
    }
    [evidence] = _brief_claim(claim)["evidence"]
    assert len(evidence["quote"].split()) == QUOTE_WORDS + 1  # the words and an ellipsis
    assert "text" not in evidence


def test_an_unpriced_paid_model_is_refused_not_counted_as_free():
    meter = UsageMeter(FakeOpenAI(), max_usd=0.0001)
    chat = OpenAIChat(model="gpt-4o", client=meter, provider="openai")
    with pytest.raises(ValueError, match="No price for gpt-4o"):
        chat.complete([{"role": "user", "content": "hi"}])
    assert meter.totals == {}  # refused before the call was made
    local = UsageMeter(FakeOpenAI(), require_prices=False)  # e.g. Ollama: free
    OpenAIChat(model="qwen3:8b", client=local, provider="openai").complete([])
    assert local.cost() == 0 and local.totals["qwen3:8b"]["calls"] == 1


def test_spending_limit_keeps_finished_rows_and_marks_the_report(tmp_path):
    items = [
        {
            "id": i,
            "expected_sources": ["course"],
            "expected_correctness": "correct",
            "gold_docs": [],
        }
        for i in ("a", "b", "c")
    ]
    calls = []

    def agentic(item):
        calls.append(item["id"])
        if item["id"] == "b":
            raise SpendLimitReached("Budget spent: US$1.0000 of US$1.0")
        return pack()

    report = compare(items, agentic, lambda item: pack())
    assert [r["id"] for r in report["single_pass"]["rows"]] == ["a", "b", "c"]
    assert [r["id"] for r in report["agentic"]["rows"]] == ["a"]  # b interrupted, c not run
    assert calls == ["a", "b"] and "at agentic b" in report["stopped"]
    report["config"] = {
        "model": "m",
        "embedder": "e",
        "web": None,
        "items": "x",
        "corpus": "c",
        "seed": 42,
        "run_at": "now",
    }
    table = research_eval.write_results(report, items, tmp_path, "partial").with_suffix(".md")
    text = table.read_text()
    assert "Stopped early" in text and "| c | correct |" in text and "not run" in text


def test_spending_limit_inside_a_tool_stops_the_run(store, schedule):
    """Research's tool handler reports most failures to the model; the spending limit must not
    be one of them."""

    def spent(claim, passages):
        raise SpendLimitReached("Budget spent")

    claim = "People keep three apps and drivers switch between them."
    llm = ScriptedLLM(
        [
            turn(call("search_course_materials", query="multi-homing riders drivers")),
            lambda m: turn(call("grade_evidence", claim=claim, chunks=ids_in(last_tool_result(m)))),
        ],
        grader=spent,
    )
    item = {"id": "x", "date": "2026-09-01", "text": claim, "expected_sources": ["course"]}
    agent = ResearchAgent(llm, store, schedule)
    report = research_eval.run_comparison([item], agent, None)
    assert report["single_pass"]["rows"] == [] and "at single_pass x" in report["stopped"]
    assert "agentic" not in report
