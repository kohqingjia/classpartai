"""Judge agent trajectory/output evaluation: agreement with human scores, and how it got there.

uv run python eval/judge_eval.py                  # writes eval/results/judge-<time>.json
uv run python eval/judge_eval.py --only i03 i18   # a few cases
uv run python eval/judge_eval.py --evidence none  # the Judge without Research's findings

Needs a model: OPENAI_API_KEY in .env (see .env.example). Costs one Judge run per case.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from classpartai import config
from classpartai.models import configured_driver
from classpartai.participation.judge_evaluate import evaluate, format_table, load_cases


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--items", default=f"{config.COURSE_DIR}/eval_contributions.jsonl")
    parser.add_argument("--labels", default=f"{config.COURSE_DIR}/judge_labels.jsonl")
    parser.add_argument("--only", nargs="*", help="case ids to run, e.g. i03 i18")
    parser.add_argument(
        "--evidence",
        choices=["labels", "none"],
        default="labels",
        help="labels: hand the Judge what a perfect Research agent would report",
    )
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("No model configured: set OPENAI_API_KEY in .env (see .env.example).")
    config.set_seed()
    cases = load_cases(args.items, args.labels)
    if args.only:
        cases = [c for c in cases if c["id"] in set(args.only)]
    unreviewed = [c["id"] for c in cases if not c["reviewed"]]
    if unreviewed:
        print(
            f"Note: {len(unreviewed)} of {len(cases)} human scores are still drafts (not reviewed)."
        )

    report = evaluate(cases, lambda case: configured_driver, args.evidence)
    report["config"] = {
        "model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
        "evidence": args.evidence,
        "items": args.items,
        "labels": args.labels,
        "unreviewed_labels": unreviewed,
        "seed": config.SEED,
    }

    print(format_table(report))
    print("\nPer case (human -> Judge):")
    for row in report["rows"]:
        shown = row["predicted"] if row["finished"] else row["error"]
        print(f"  {row['id']}: {row['expected']} -> {shown}  [{len(row['trajectory'])} tool calls]")
    out = Path("eval/results") / f"judge-{datetime.now():%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull results: {out}")


if __name__ == "__main__":
    main()
