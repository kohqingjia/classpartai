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
"""

from __future__ import annotations

import json
from pathlib import Path

from classpartai.research.agent import EvidencePack
from classpartai.research.materials import matches


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
        "needs_review": pack.needs_review,
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
)


def summarise(rows: list[dict]) -> dict:
    out = {}
    for key in METRICS:
        values = [float(r[key]) for r in rows if r[key] is not None]
        out[key] = round(sum(values) / len(values), 3) if values else None
    return out


def compare(items: list[dict], run_agentic, run_single_pass) -> dict:
    """run_*(item) -> EvidencePack. Returns per-item rows and a summary for each system."""
    report = {}
    for name, runner in (("single_pass", run_single_pass), ("agentic", run_agentic)):
        rows = []
        for item in items:
            row = score(item, runner(item))
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
    return report


def format_table(report: dict) -> str:
    names = [n for n in ("single_pass", "agentic") if n in report]
    lines = ["| metric | " + " | ".join(names) + " |", "|---|" + "---|" * len(names)]
    for key in METRICS:
        cells = []
        for name in names:
            value = report[name]["summary"][key]
            cells.append("n/a" if value is None else f"{value:.2f}")
        lines.append(f"| {key} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
