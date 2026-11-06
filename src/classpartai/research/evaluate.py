"""Score Research runs against labelled question-and-answer pairs: single-pass vs agentic RAG.

Each labelled item (data/is469/eval_contributions.jsonl) has the professor's question, the
student's answer, and labels: the sources a good run should search ("none", "course", "web"),
whether the answer is correct, whether it answers the question, and the files that hold the gold
evidence (paths or patterns such as "*Topic8*"). Metrics, averaged over the items each applies to:

    routed_correctly   searched every expected source, and the web only if expected (R1)
    correctness_ok     correct / partially_correct / incorrect matches the label
    answers_question_ok  yes / partly / no matches the label (the agent only)
    reasoning_ok       explained / asserted / none matches the label, where labelled
    mistake_ok         reasonable_guess / misconception / unsupported / none matches, where labelled
    context_precision  share of the evidence passed to the Judge that comes from a gold file
    gold_hit           at least one gold file is in the evidence passed to the Judge
    quoted             share of that evidence with a verbatim quote the Auditor can check
    llm_calls, searches, seconds   what it cost
    tokens, usd        model tokens and their price, when the runs go through a UsageMeter
"""

from __future__ import annotations

import json
from pathlib import Path

from classpartai.research.agent import EvidencePack
from classpartai.research.materials import matches

# US$ per million tokens: (input, cached input, output). OpenAI's list prices, November 2026.
PRICES = {
    "gpt-5-mini": (0.25, 0.025, 2.00),
    "text-embedding-3-small": (0.02, 0.02, 0.0),
}
QUOTE_WORDS = 25  # quotes in saved results are cut to this many words (the slides aren't ours)


def load_labelled(path: str | Path) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def score(item: dict, pack: EvidencePack) -> dict:
    expected = set(item.get("expected_sources") or [])
    searched = set() if pack.route == "none" else set(pack.route.split("+"))
    if expected == {"none"}:
        routed = not searched
    else:
        routed = expected <= searched and ("web" in expected or "web" not in searched)
    evidence = [e for c in pack.claims + pack.expected_points for e in c["evidence"]]
    course = [e for e in evidence if e["source_type"] != "web"]
    gold = list(item.get("gold_docs") or [])  # file paths or patterns such as "*Topic8*"
    expected_correctness = item.get("expected_correctness")
    expected_answers = item.get("expected_answers_question")
    return {
        "id": item["id"],
        "route": pack.route,
        "correctness": pack.correctness,
        "answers_question": pack.answers_question,
        "routed_correctly": routed,
        "correctness_ok": (pack.correctness == expected_correctness)
        if expected_correctness
        else None,
        "answers_question_ok": (pack.answers_question == expected_answers)
        if expected_answers
        else None,
        "reasoning_ok": (pack.reasoning == item["expected_reasoning"])
        if item.get("expected_reasoning")
        else None,
        # expected_mistake may be null, meaning "no mistake should be reported"
        "mistake_ok": ((pack.mistake or {}).get("type") == item["expected_mistake"])
        if "expected_mistake" in item
        else None,
        "context_precision": (sum(matches(e["doc"], gold) for e in course) / len(course))
        if gold and course
        else (0.0 if gold else None),
        "gold_hit": any(matches(e["doc"], gold) for e in course) if gold else None,
        "quoted": (sum(bool(e["quote"]) for e in evidence) / len(evidence)) if evidence else None,
        "llm_calls": pack.usage.get("llm_calls", 0),
        "searches": pack.usage.get("course_searches", 0) + pack.usage.get("web_searches", 0),
        "seconds": pack.usage.get("seconds", 0.0),
        "tokens": None,
        "usd": None,
        "needs_review": pack.needs_review,
        "claims": [_brief_claim(c) for c in pack.claims],
    }


def _short(text: str, words: int = QUOTE_WORDS) -> str:
    said = (text or "").split()
    return " ".join(said[:words]) + (" ..." if len(said) > words else "")


def _brief_claim(claim: dict) -> dict:
    """A claim's verdict and where its evidence came from, each quote cut to QUOTE_WORDS."""
    return {
        "claim": claim["claim"],
        "status": claim["status"],
        "evidence": [
            {
                "doc": e.get("doc") or e.get("url"),
                "page": e.get("page"),
                "relevance": e.get("relevance"),
                "stance": e.get("stance"),
                "quote": _short(e.get("quote", "")),
            }
            for e in claim["evidence"]
        ],
    }


METRICS = (
    "routed_correctly",
    "correctness_ok",
    "answers_question_ok",
    "reasoning_ok",
    "mistake_ok",
    "context_precision",
    "gold_hit",
    "quoted",
    "llm_calls",
    "searches",
    "seconds",
    "tokens",
    "usd",
)


def summarise(rows: list[dict]) -> dict:
    out = {}
    for key in METRICS:
        values = [float(r[key]) for r in rows if r.get(key) is not None]
        out[key] = round(sum(values) / len(values), 6 if key == "usd" else 3) if values else None
    return out


def compare(items: list[dict], run_agentic, run_single_pass, meter=None) -> dict:
    """run_*(item) -> EvidencePack. Returns per-item rows and a summary for each system. With a
    UsageMeter that the runs' models call through, each row also gets its tokens and cost, and
    each system its usage by model, total cost and total time."""
    report = {}
    for name, runner in (("single_pass", run_single_pass), ("agentic", run_agentic)):
        rows = []
        system_start = meter.snapshot() if meter else None
        for item in items:
            before = meter.snapshot() if meter else None
            row = score(item, runner(item))
            if meter:
                spent = meter.since(before)
                row["tokens"] = sum(m["input"] + m["output"] for m in spent.values())
                row["usd"] = round(meter.cost(spent), 6)
            if name == "single_pass":  # no routing, no view on the question or answer quality
                for key in (
                    "routed_correctly",
                    "answers_question_ok",
                    "reasoning_ok",
                    "mistake_ok",
                ):
                    row[key] = None
            rows.append(row)
        report[name] = {"summary": summarise(rows), "rows": rows}
        if meter:
            spent = meter.since(system_start)
            report[name]["usage"] = {
                "by_model": spent,
                "usd": round(meter.cost(spent), 6),
                "seconds_total": round(sum(r["seconds"] for r in rows), 2),
            }
    return report


class UsageMeter:
    """Stands in for an OpenAI client: passes chat and embedding calls through and adds up the
    tokens each reports, by model, so a comparison can say what each system cost. Raises before
    a call once ``max_usd`` has been spent."""

    def __init__(self, client, prices: dict = PRICES, max_usd: float | None = None):
        self.client, self.prices, self.max_usd = client, prices, max_usd
        self.totals: dict[str, dict] = {}
        self.chat = _Namespace(completions=_Namespace(create=self._chat))
        self.embeddings = _Namespace(create=self._embed)

    def _add(self, model: str, prompt: int, cached: int, output: int) -> None:
        row = self.totals.setdefault(model, {"calls": 0, "input": 0, "cached": 0, "output": 0})
        row["calls"] += 1
        row["input"] += prompt
        row["cached"] += cached
        row["output"] += output

    def _check(self) -> None:
        if self.max_usd is not None and self.cost() >= self.max_usd:
            raise RuntimeError(f"Budget spent: US${self.cost():.4f} of US${self.max_usd}")

    def _chat(self, **kwargs):
        self._check()
        response = self.client.chat.completions.create(**kwargs)
        usage = getattr(response, "usage", None)
        details = getattr(usage, "prompt_tokens_details", None)
        self._add(
            kwargs["model"],
            getattr(usage, "prompt_tokens", 0) or 0,
            getattr(details, "cached_tokens", 0) or 0,
            getattr(usage, "completion_tokens", 0) or 0,
        )
        return response

    def _embed(self, **kwargs):
        self._check()
        response = self.client.embeddings.create(**kwargs)
        usage = getattr(response, "usage", None)
        self._add(kwargs["model"], getattr(usage, "prompt_tokens", 0) or 0, 0, 0)
        return response

    def snapshot(self) -> dict[str, dict]:
        return {model: dict(row) for model, row in self.totals.items()}

    def since(self, before: dict[str, dict]) -> dict[str, dict]:
        """Usage by model since ``snapshot()`` returned ``before``."""
        out = {}
        for model, row in self.totals.items():
            old = before.get(model, {})
            spent = {k: v - old.get(k, 0) for k, v in row.items()}
            if spent["calls"]:
                out[model] = spent
        return out

    def cost(self, usage: dict[str, dict] | None = None) -> float:
        """US$ for ``usage`` (default: everything so far). A model without a price counts as
        free, e.g. a local Ollama model."""
        total = 0.0
        for model, row in (self.totals if usage is None else usage).items():
            price = next((p for name, p in self.prices.items() if model.startswith(name)), None)
            if price is None:
                continue
            fresh = row["input"] - row["cached"]
            total += (fresh * price[0] + row["cached"] * price[1] + row["output"] * price[2]) / 1e6
        return total


class _Namespace:
    def __init__(self, **attrs):
        self.__dict__.update(attrs)


def format_table(report: dict) -> str:
    names = [n for n in ("single_pass", "agentic") if n in report]
    lines = ["| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for key in METRICS:
        cells = []
        for name in names:
            value = report[name]["summary"][key]
            if value is None:
                cells.append("n/a")
            elif key == "usd":
                cells.append(f"{value:.4f}")
            elif key == "tokens":
                cells.append(f"{value:.0f}")
            else:
                cells.append(f"{value:.2f}")
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
