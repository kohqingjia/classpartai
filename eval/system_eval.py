"""End-to-end evaluation: each demo seminar through the whole system, Coordinator to emails.

    uv run python eval/system_eval.py                        # all seven (needs OPENAI_API_KEY)
    uv run python eval/system_eval.py --only 02-one-silent --max-usd 1
    uv run python eval/system_eval.py --documents var/library/documents.json   # the real slides

Runs the same ``coordinate`` entry point as the app, on a throwaway database, with email in test
mode (nothing can be sent: the workflow has no send tool). Writes eval/results/system-<time>.md
and .json: per session, the automatic checks (finished, everyone covered, the edge case handled,
the agents handing work to each other), what each agent cost, and the questions a person answers
when reading the same outputs. See src/classpartai/system_eval.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Before classpartai.config is imported: these are read at import time.
os.environ.setdefault("CLASSPARTAI_DATA_DIR", tempfile.mkdtemp(prefix="system-eval-data-"))
os.environ["RESEARCH_BRIDGE_WEB"] = "false"
os.environ["EMAIL_TEST_MODE"] = "true"

from classpartai import config  # noqa: E402
from classpartai.participation.adversarial import Meter, run_inputs  # noqa: E402
from classpartai.system_eval import (  # noqa: E402
    evaluate,
    load_documents,
    markdown,
    seminars,
    sheet,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="seminar ids, e.g. 02-one-silent")
    parser.add_argument("--documents", help="a course library documents.json (default: demo notes)")
    parser.add_argument("--max-usd", type=float, default=3.0, help="stop once this is spent")
    parser.add_argument("--out", default="eval/results")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set: this evaluation runs the real model.")

    config.set_seed()
    config.FEEDBACK_JUDGE = True  # score every email against the rubric (LLM-as-judge)
    meter = Meter(args.max_usd)
    for model in (config.OPENAI_MODEL, config.OPENAI_EMBEDDING_MODEL):
        try:
            meter.check(model)  # fail now, not mid-run, on a model without a price
        except RuntimeError as error:
            sys.exit(str(error))
    meter.install()
    docs = load_documents(Path(args.documents) if args.documents else None)
    workdir = Path(tempfile.mkdtemp(prefix="system-eval-"))
    results, errors = [], []
    for seminar in seminars(docs, args.only):
        if meter.usd >= args.max_usd:
            print(f"Cost cap reached; skipping {seminar.id}", flush=True)
            continue
        print(f"Running {seminar.id} ...", flush=True)
        try:
            run = run_inputs(seminar.id, seminar.inputs, workdir, name=seminar.id)
            result = evaluate(seminar, run)
        except Exception as exc:  # report it, keep going with the other sessions
            errors.append({"id": seminar.id, "error": f"{type(exc).__name__}: {exc}"[:300]})
            print(f"  harness error: {errors[-1]['error']}", flush=True)
            continue
        results.append(result)
        print(
            f"  {result['passed']}/{result['total']} checks, {result['seconds']:.0f}s", flush=True
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    meta = {
        "stamp": stamp,
        "model": config.OPENAI_MODEL,
        "seed": config.SEED,
        "documents": args.documents or "data/course_materials.json (demo notes)",
        "totalUsd": round(meter.usd, 4),
    }
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    report = markdown(results, meta)
    (out / f"system-{stamp}.md").write_text(report, encoding="utf-8")
    (out / f"system-{stamp}.json").write_text(
        json.dumps({**meta, "sessions": results, "errors": errors}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out / f"qualitative-{stamp}.md").write_text(sheet(results, stamp), encoding="utf-8")
    print(report)
    print(f"Wrote {out}/system-{stamp}.md and .json")


if __name__ == "__main__":
    main()
