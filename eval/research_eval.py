"""Research evaluation: single-pass RAG vs agentic RAG on labelled question-and-answer pairs.

Search either the lecture files' index or a course library's documents (what the app searches):

uv run python -m classpartai.research ingest      # once, to build the index from data/raw/is469
uv run python eval/research_eval.py               # writes eval/results/research-<time>.{json,md}

uv run python eval/research_eval.py --documents var/library/documents.json --max-usd 1

The JSON has every item's scores, claim verdicts and evidence (quotes cut to 25 words, since the
slides are the instructor's), and each system's tokens, cost and time; the Markdown has the
tables. Results under eval/results/ may be committed; the documents may not.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from classpartai import config
from classpartai.assessment import Document
from classpartai.llm import Embedder, OpenAIChat, OpenAIEmbedder, make_client
from classpartai.research import ResearchAgent, single_pass
from classpartai.research.bridge import session_store
from classpartai.research.evaluate import (
    QUOTE_WORDS,
    UsageMeter,
    compare,
    format_table,
    load_labelled,
)
from classpartai.research.materials import load_schedule
from classpartai.research.store import VectorStore
from classpartai.research.web import default_web_search


def load_documents(path: str | Path) -> list[Document]:
    """A course library's documents.json ([{file, uploadedAt, document}]) or a plain list of
    session documents (what ``python -m classpartai.research export-documents`` writes)."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Document.model_validate(e.get("document", e)) for e in raw]


def build_store(
    documents: list[Document],
    embedder: Embedder,
    schedule: dict,
    cache_dir: str | Path | None = None,
) -> VectorStore:
    """The documents indexed the way a session indexes them (bridge.session_chunks)."""
    return session_store(SimpleNamespace(documents=documents), embedder, schedule, cache_dir)


def build_agent(meter: UsageMeter, documents=None, cache_dir=None) -> ResearchAgent:
    """Research on the configured models, every call going through ``meter``."""
    chat, embedder = OpenAIChat(client=meter), OpenAIEmbedder(client=meter)
    schedule = load_schedule(config.COURSE_DIR)
    if documents is None:
        store = VectorStore.load(config.INDEX_DIR, embedder)
    else:
        store = build_store(documents, embedder, schedule, cache_dir)
    return ResearchAgent(
        chat,
        store,
        schedule,
        default_web_search(),
        max_steps=config.RESEARCH_MAX_STEPS,
        max_course_searches=config.RESEARCH_MAX_COURSE_SEARCHES,
        max_web_searches=config.RESEARCH_MAX_WEB_SEARCHES,
        max_grades=config.RESEARCH_MAX_GRADES,
    )


def run_comparison(items: list[dict], agent: ResearchAgent, meter: UsageMeter | None) -> dict:
    return compare(
        items,
        run_agentic=lambda item: agent.run(
            item["text"],
            date=item["date"],
            question=item.get("question"),
            contribution_id=item["id"],
        ),
        run_single_pass=lambda item: single_pass(
            item["text"],
            item["date"],
            agent.llm,
            agent.store,
            agent.schedule,
            question=item.get("question"),
            contribution_id=item["id"],
        ),
        meter=meter,
    )


SYSTEMS = ("single_pass", "agentic")


def _cell(value) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "✓" if value else "✗"
    return str(value)


def markdown(report: dict, items: list[dict]) -> str:
    cfg = report["config"]
    lines = [
        "# Research: single-pass RAG vs agentic RAG",
        "",
        f"{len(items)} labelled items ({cfg['items']}), run {cfg['run_at']}. Model "
        f"`{cfg['model']}`, embedder `{cfg['embedder']}`, web search `{cfg['web']}`, corpus "
        f"{cfg['corpus']}, seed {cfg['seed']}. Means over the items each metric applies to "
        "(definitions in `src/classpartai/research/evaluate.py`); seconds, tokens and usd are "
        "per item.",
        "",
        format_table(report),
        "",
    ]
    if report.get("stopped"):
        lines += [f"**Stopped early, results incomplete:** {report['stopped']}.", ""]
    lines += [
        "Totals per system (API calls are chat and query-embedding calls; output tokens include "
        "the model's reasoning tokens):",
        "",
        "| system | API calls | input tokens | output tokens | US$ total | seconds total |",
        "|---|---|---|---|---|---|",
    ]
    for name in SYSTEMS:
        usage = report.get(name, {}).get("usage")
        if not usage:
            continue
        models = usage["by_model"].values()
        calls = sum(m["calls"] for m in models)
        prompt = sum(m["input"] for m in models)
        output = sum(m["output"] for m in models)
        lines.append(
            f"| {name} | {calls} | {prompt} | {output} | {usage['usd']:.4f} | "
            f"{usage['seconds_total']:.1f} |"
        )
    if "index_usage" in report:
        lines.append(f"\nIndexing the corpus: US${report['index_usage']['usd']:.4f}.")
    lines += [
        "",
        "## Per item",
        "",
        "Correctness as labelled / single-pass / agentic; the agent's route and whether it",
        "found a gold file.",
        "",
        "| id | label | single-pass | agentic | route | routed ok | answers q (label / agent) "
        "| gold hit (sp / agent) |",
        "|---|---|---|---|---|---|---|---|",
    ]
    single, agentic = ({r["id"]: r for r in report.get(n, {}).get("rows", [])} for n in SYSTEMS)
    not_run = {k: None for k in ("correctness", "correctness_ok", "gold_hit")}
    not_run |= {"route": "not run", "routed_correctly": None, "answers_question": None}
    for item in items:
        if item["id"] not in single and item["id"] not in agentic:
            continue
        sp, row = single.get(item["id"], not_run), agentic.get(item["id"], not_run)
        lines.append(
            f"| {item['id']} | {_cell(item.get('expected_correctness'))} | "
            f"{_cell(sp['correctness'])} {_cell(sp['correctness_ok'])} | "
            f"{_cell(row['correctness'])} {_cell(row['correctness_ok'])} | {row['route']} | "
            f"{_cell(row['routed_correctly'])} | "
            f"{_cell(item.get('expected_answers_question'))} / {_cell(row['answers_question'])} | "
            f"{_cell(sp['gold_hit'])} / {_cell(row['gold_hit'])} |"
        )
    return "\n".join(lines) + "\n"


def write_results(report: dict, items: list[dict], out_dir: str | Path, stem: str) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out / f"{stem}.md").write_text(markdown(report, items), encoding="utf-8")
    return out / stem


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", default=f"{config.COURSE_DIR}/eval_contributions.jsonl")
    parser.add_argument("--only", nargs="*", help="item ids to run, e.g. e05 e11")
    parser.add_argument(
        "--documents",
        help="course library documents.json to search instead of the index in INDEX_DIR",
    )
    parser.add_argument("--index-cache", default=str(config.DATA_DIR / "research-index"))
    parser.add_argument("--max-usd", type=float, help="stop once this much has been spent")
    parser.add_argument("--out", default="eval/results")
    parser.add_argument("--name", help="file stem (default research-<time>)")
    parser.add_argument(
        "--effort",
        choices=["minimal", "low", "medium", "high"],
        help="reasoning effort for every call; the experiment compares low with the default "
        "(see 'Research: reasoning effort' on the Experiments tab)",
    )
    args = parser.parse_args()
    if args.effort:
        config.LLM_REASONING_EFFORT = args.effort

    config.set_seed()
    items = load_labelled(args.items)
    if args.only:
        items = [i for i in items if i["id"] in set(args.only)]
    meter = UsageMeter(
        make_client(config.LLM_PROVIDER),
        max_usd=args.max_usd,
        require_prices=config.LLM_PROVIDER != "ollama",  # local models are free
    )
    documents = load_documents(args.documents) if args.documents else None
    agent = build_agent(meter, documents, args.index_cache)
    index_usage = {"by_model": meter.snapshot(), "usd": round(meter.cost(), 6)}

    report = run_comparison(items, agent, meter)
    report["index_usage"] = index_usage
    report["config"] = {
        "model": agent.llm.name,
        "embedder": agent.store.embedder.name,
        "web": agent.web.name if agent.web else None,
        "items": args.items,
        "corpus": (
            f"{len(documents)} library documents, {len(agent.store.chunks)} chunks"
            if documents
            else f"index {config.INDEX_DIR}, {len(agent.store.chunks)} chunks"
        ),
        "documents": [d.source for d in documents] if documents else None,
        "reasoning_effort": config.LLM_REASONING_EFFORT,
        "budgets": {"max_steps": agent.max_steps, **agent.budgets},
        "seed": config.SEED,
        "quote_words": QUOTE_WORDS,
        "run_at": f"{datetime.now():%Y-%m-%d %H:%M}",
        "usd_total": round(meter.cost(), 6),
    }

    print(format_table(report))
    print(f"\nSpent US${meter.cost():.4f} in total")
    if report.get("stopped"):
        print(f"Stopped early, results incomplete: {report['stopped']}")
    stem = args.name or f"research-{datetime.now():%Y%m%d-%H%M%S}"
    path = write_results(report, items, args.out, stem)
    print(f"Results: {path}.json, {path}.md")


if __name__ == "__main__":
    main()
