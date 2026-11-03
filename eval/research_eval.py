"""Research evaluation: single-pass RAG vs agentic RAG on labelled question-and-answer pairs.

uv run python -m classpartai.research ingest      # once, to build the index
uv run python eval/research_eval.py               # writes eval/results/research-<time>.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from classpartai import config
from classpartai.research import ResearchAgent, single_pass
from classpartai.research.evaluate import compare, format_table, load_labelled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", default=f"{config.COURSE_DIR}/eval_contributions.jsonl")
    parser.add_argument("--only", nargs="*", help="item ids to run, e.g. e05 e11")
    args = parser.parse_args()

    config.set_seed()
    items = load_labelled(args.items)
    if args.only:
        items = [i for i in items if i["id"] in set(args.only)]
    agent = ResearchAgent.from_config()

    report = compare(
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
        ),
    )
    report["config"] = {
        "model": agent.llm.name,
        "embedder": agent.store.embedder.name,
        "web": agent.web.name if agent.web else None,
        "items": args.items,
        "seed": config.SEED,
    }

    print(format_table(report))
    print("\nPer contribution (agentic):")
    for row in report["agentic"]["rows"]:
        print(
            f"  {row['id']}: route={row['route']:10s} correctness={row['correctness']} "
            f"({'ok' if row['correctness_ok'] else row['correctness_ok']}) "
            f"answers_question={row['answers_question']} "
            f"({'ok' if row['answers_question_ok'] else row['answers_question_ok']}) "
            f"routed={row['routed_correctly']}"
        )
    out = Path("eval/results") / f"research-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nFull results: {out}")


if __name__ == "__main__":
    main()
