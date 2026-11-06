"""Adversarial guardrail evaluation: run every case in eval/guardrails/cases/ through the real
assessment workflow and report what the guardrails caught.

    uv run python eval/guardrails/run.py                  # all cases (needs OPENAI_API_KEY)
    uv run python eval/guardrails/run.py --only 01-direct-injection --max-usd 0.5

Writes eval/results/guardrails-<time>.md (the results table) and .json (per-case tokens, cost,
latency and the run's actions). The cases and their checks are in
src/classpartai/participation/adversarial.py; the deterministic guardrails are tested without a
model in tests/test_guardrails.py.

Runs on a throwaway data directory, with web search off (so results depend only on the case
files) and email in test mode. Nothing can be sent: the workflow has no send tool and the
human-gate probe uses a recording transport.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

# Before classpartai.config is imported: these are read at import time.
os.environ.setdefault("CLASSPARTAI_DATA_DIR", tempfile.mkdtemp(prefix="guardrails-data-"))
os.environ["RESEARCH_BRIDGE_WEB"] = "false"
os.environ["EMAIL_TEST_MODE"] = "true"

from classpartai import config  # noqa: E402
from classpartai.participation.adversarial import CASES, run_case  # noqa: E402

# US$ per million tokens (OpenAI list prices for the models this project uses).
PRICES = {
    "gpt-5-mini": {"input": 0.25, "cached": 0.025, "output": 2.00},
    "text-embedding-3-small": {"input": 0.02, "cached": 0.02, "output": 0.0},
}


class Meter:
    """Counts the tokens and cost of every OpenAI call, by wrapping the SDK's create methods.
    Instrumentation only: requests and responses pass through unchanged. Once ``max_usd`` is
    spent, further calls raise, which stops the run in progress as a provider failure."""

    def __init__(self, max_usd: float):
        self.max_usd = max_usd
        self.calls: list[dict] = []

    @property
    def usd(self) -> float:
        return sum(c["usd"] for c in self.calls)

    def install(self) -> None:
        from openai.resources.chat.completions import Completions
        from openai.resources.embeddings import Embeddings

        meter = self

        def wrap(original, kind):
            def create(self, *args, **kwargs):
                if meter.usd >= meter.max_usd:
                    raise RuntimeError(f"Evaluation cost cap of US${meter.max_usd} reached")
                started = time.perf_counter()
                response = original(self, *args, **kwargs)
                meter.record(kind, kwargs.get("model", ""), response, time.perf_counter() - started)
                return response

            return create

        Completions.create = wrap(Completions.create, "chat")
        Embeddings.create = wrap(Embeddings.create, "embedding")

    def record(self, kind: str, model: str, response, seconds: float) -> None:
        usage = getattr(response, "usage", None)
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        output = getattr(usage, "completion_tokens", 0) or 0
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0
        reasoning = getattr(
            getattr(usage, "completion_tokens_details", None), "reasoning_tokens", 0
        )
        price = next((p for name, p in PRICES.items() if model.startswith(name)), None)
        usd = (
            (
                (prompt - cached) * price["input"]
                + cached * price["cached"]
                + output * price["output"]
            )
            / 1e6
            if price
            else 0.0
        )
        self.calls.append(
            {
                "kind": kind,
                "model": model,
                "prompt": prompt,
                "cached": cached,
                "output": output,
                "reasoning": reasoning or 0,
                "usd": usd,
                "priced": price is not None,
                "seconds": round(seconds, 2),
            }
        )

    def since(self, start: int) -> dict:
        calls = self.calls[start:]
        return {
            "openaiCalls": len(calls),
            "promptTokens": sum(c["prompt"] for c in calls),
            "cachedTokens": sum(c["cached"] for c in calls),
            "outputTokens": sum(c["output"] for c in calls),
            "reasoningTokens": sum(c["reasoning"] for c in calls),
            "usd": round(sum(c["usd"] for c in calls), 4),
            "unpricedCalls": sum(1 for c in calls if not c["priced"]),
        }


def cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="*", help="case ids to run, e.g. 01-direct-injection")
    parser.add_argument("--max-usd", type=float, default=2.5, help="stop once this is spent")
    parser.add_argument("--out", default="eval/results")
    args = parser.parse_args()
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set: this evaluation runs the real model.")

    config.set_seed()
    meter = Meter(args.max_usd)
    meter.install()
    cases = [c for c in CASES if not args.only or c.id in set(args.only)]
    rows, details = [], []
    for case in cases:
        if meter.usd >= args.max_usd:
            print(f"Cost cap reached; skipping {case.id}", flush=True)
            details.append({"case": case.id, "skipped": "cost cap"})
            continue
        print(f"Running {case.id} ...", flush=True)
        start, started = len(meter.calls), time.perf_counter()
        try:
            runs = run_case(case)
            verdict = case.check(runs)
            error = None
        except Exception as exc:  # report it, keep going with the other cases
            runs, verdict, error = [], None, f"{type(exc).__name__}: {exc}"[:300]
        seconds = time.perf_counter() - started
        usage = meter.since(start)
        # A provider failure (or a harness error) says nothing about the guardrail.
        failed = error or any(r.run.get("stop_reason") == "provider_failure" for r in runs)
        caught = "yes" if verdict and verdict.caught else "inconclusive" if failed else "no"
        observed = verdict.observed if verdict else f"harness error: {error}"
        print(f"  caught: {caught}: {observed}", flush=True)
        print(f"  {usage['usd']:.4f} USD, {seconds:.0f}s (total {meter.usd:.4f} USD)", flush=True)
        rows.append((case, observed, caught, usage, seconds))
        details.append(
            {
                "case": case.id,
                "attack": case.attack,
                "expected": case.expected,
                "guardrail": case.guardrail,
                "caught": caught,
                "observed": observed,
                "error": error,
                "seconds": round(seconds, 1),
                "usage": usage,
                "runs": [
                    {
                        "file": f,
                        "status": r.run.get("status"),
                        "stopReason": r.run.get("stop_reason"),
                        "workflowTokens": r.progress.get("tokens"),
                        "modelCalls": r.progress.get("modelCalls"),
                        "toolCalls": r.progress.get("toolCalls"),
                        "elapsedSeconds": round(r.seconds, 1),
                        "actions": [
                            {"tool": a["tool"], "outcome": a["outcome"], "summary": a["summary"]}
                            for a in r.progress.get("actions", [])
                        ],
                        "findings": [f.model_dump() for f in r.draft.content.findings]
                        if r.draft
                        else [],
                        "auditIssues": [i.model_dump() for i in r.draft.content.audit.issues]
                        if r.draft
                        else [],
                        "gate": r.gate,
                    }
                    for f, r in zip(case.files, runs, strict=False)
                ],
            }
        )

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    caught = sum(1 for r in rows if r[2] == "yes")
    inconclusive = sum(1 for r in rows if r[2] == "inconclusive")
    lines = [
        f"# Guardrail evaluation, {stamp}",
        "",
        f"Model: {config.OPENAI_MODEL}; evidence agent: {config.EVIDENCE_AGENT} (web off); "
        f"caught {caught}/{len(rows)}"
        + (f" ({inconclusive} inconclusive)" if inconclusive else "")
        + f"; cost US${meter.usd:.2f}.",
        "",
        "| Case | Attack | Expected | Observed | Caught? | Guardrail | Tokens | Latency |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for case, observed, ok, usage, seconds in rows:
        tokens = usage["promptTokens"] + usage["outputTokens"]
        lines.append(
            "| "
            + " | ".join(
                cell(x)
                for x in (
                    case.id,
                    case.attack,
                    case.expected,
                    observed,
                    "**no**" if ok == "no" else ok,
                    case.guardrail,
                    f"{tokens:,}",
                    f"{seconds:.0f}s",
                )
            )
            + " |"
        )
    report = {
        "stamp": stamp,
        "model": config.OPENAI_MODEL,
        "evidenceAgent": config.EVIDENCE_AGENT,
        "web": False,
        "seed": config.SEED,
        "totalUsd": round(meter.usd, 4),
        "caught": caught,
        "cases": details,
    }
    (out / f"guardrails-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out / f"guardrails-{stamp}.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("\n".join(lines))
    print(f"\nWrote {out}/guardrails-{stamp}.md and .json")


if __name__ == "__main__":
    main()
