"""Before and after, side by side: every comparison the team has run, from the committed results.

The dashboard's third tab. Each experiment is two systems on the same inputs, scored the same way:
agentic RAG against single-pass RAG, the Listener before and after its fixes, the injection screen
before and after widening, the guardrail suite without and with the Auditor agent. A row is read
from ``eval/results/*.json``, never typed in, so the page cannot drift from the results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from classpartai.config import REPO_ROOT

RESULTS = REPO_ROOT / "eval" / "results"


@dataclass(frozen=True)
class Metric:
    name: str
    before: float
    after: float
    better: str  # "higher" or "lower"
    kind: str = "score"  # score (0 to 1), count, usd, seconds: how it is written and charted


@dataclass(frozen=True)
class Experiment:
    title: str
    before: str
    after: str
    metrics: list[Metric]
    reading: str
    source: str


def _json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def fmt(value: float, kind: str) -> str:
    return {
        "score": f"{value:.0%}",
        "usd": f"${value:,.4f}",
        "seconds": f"{value:,.0f} s",
    }.get(kind, f"{value:,.2f}".rstrip("0").rstrip("."))


def verdict(m: Metric) -> str:
    if m.before == m.after:
        return "⚪ same"
    good = (m.after > m.before) == (m.better == "higher")
    return "🟢 better" if good else "🔴 worse"


def change(m: Metric) -> str:
    if m.before in (0, None):
        return "—"
    return f"{m.after / m.before:.1f}×"


def research() -> Experiment | None:
    d = _json(RESULTS / "research-is469-library.json")
    if not d:
        return None
    one, many = d["single_pass"]["summary"], d["agentic"]["summary"]
    keys = [
        ("Correct verdicts", "correctness_ok", "higher", "score"),
        ("Context precision", "context_precision", "higher", "score"),
        ("Right passage found", "gold_hit", "higher", "score"),
        ("Quotes are exact", "quoted", "higher", "score"),
        ("Model calls per answer", "llm_calls", "lower", "count"),
        ("Tokens per answer", "tokens", "lower", "count"),
        ("Seconds per answer", "seconds", "lower", "seconds"),
        ("Cost per answer", "usd", "lower", "usd"),
    ]
    metrics = [Metric(n, one[k], many[k], b, kind) for n, k, b, kind in keys if k in one]
    cfg = d.get("config", {})
    return Experiment(
        "Research: single-pass RAG or agentic RAG",
        "Single-pass RAG",
        "Agentic RAG",
        metrics,
        f"On {cfg.get('corpus', 'the course library')} the agent gives more correct verdicts and "
        f"cleaner context, and costs {many['usd'] / one['usd']:.1f}x as much and takes "
        f"{many['seconds'] / one['seconds']:.1f}x as long per answer. A grade follows from it, "
        "so the extra cost is worth it here (Topic 8: agentic RAG has to earn its cost).",
        "eval/results/research-is469-library.json",
    )


def listener() -> Experiment | None:
    d = _json(RESULTS / "listener-20261107.json")
    if not d:
        return None
    a, b = d["A"]["totals"], d["shipped"]["totals"]
    metrics = [
        Metric(
            "Lines credited to the wrong person",
            a["wrong_person"],
            b["wrong_person"],
            "lower",
            "count",
        ),
        Metric(
            "Student lines right",
            a["student"]["correct"],
            b["student"]["correct"],
            "higher",
            "count",
        ),
        Metric(
            "Professor lines right",
            a["professor"]["correct"],
            b["professor"]["correct"],
            "higher",
            "count",
        ),
        Metric(
            "Student speech left unattributed (s)",
            a["seconds"]["unattributed"],
            b["seconds"]["unattributed"],
            "lower",
            "seconds",
        ),
    ]
    return Experiment(
        "Listener: who spoke, before and after the fixes",
        "Turn-level voice match",
        "Words to turns, line and turn checks",
        metrics,
        "Checking each word against its speaker turn and each line against its own voice stops "
        "words being credited to the wrong person. Seven scripted demo seminars; real classroom "
        "audio is untested.",
        "eval/results/listener-20261107.json",
    )


def guardrails() -> Experiment | None:
    files = sorted(RESULTS.glob("guardrails-*.json"))
    if len(files) < 2:
        return None
    old, new = _json(files[0]), _json(files[-1])
    if not old or not new:
        return None
    return Experiment(
        "Guardrails: attacks on the whole workflow",
        "Single-call model audit",
        "Auditor agent",
        [
            Metric("Attack cases caught (of 10)", old["caught"], new["caught"], "higher", "count"),
            Metric("Cost of the suite", old["totalUsd"], new["totalUsd"], "lower", "usd"),
        ],
        "The same ten cases before and after the Auditor became an agent. Cases 05 and 06 "
        "flipped between runs, so one run each is not enough to claim a gain.",
        f"eval/results/{files[0].name}, {files[-1].name}",
    )


def injection() -> Experiment | None:
    d = (
        _json(sorted(RESULTS.glob("injection-*.json"))[-1])
        if list(RESULTS.glob("injection-*.json"))
        else None
    )
    if not d:
        return None
    a, b = d["first pattern"], d["widened pattern"]
    return Experiment(
        "Listener: the injection screen",
        "First pattern",
        "Widened pattern",
        [
            Metric("Attacks caught", a["recall"], b["recall"], "higher", "score"),
            Metric(
                "Flags that were real attacks",
                a["precision"] or 0,
                b["precision"] or 0,
                "higher",
                "score",
            ),
            Metric(
                "Innocent lines flagged",
                len(a["false_alarms"]),
                len(b["false_alarms"]),
                "lower",
                "count",
            ),
        ],
        "We wrote the attacks and the widened pattern together, so its score is an upper bound, "
        "not a held-out result.",
        "eval/results/injection-*.json",
    )


def all_experiments() -> list[Experiment]:
    return [e for e in (research(), listener(), guardrails(), injection()) if e]


def table(e: Experiment) -> list[dict]:
    return [
        {
            "Measure": m.name,
            e.before: fmt(m.before, m.kind),
            e.after: fmt(m.after, m.kind),
            "Change": change(m),
            "Result": verdict(m),
        }
        for m in e.metrics
    ]


def render() -> None:
    st.caption(
        "Two systems on the same inputs, scored the same way. Every number is read from a "
        "committed result file in eval/results, so this page cannot drift from the results."
    )
    experiments = all_experiments()
    if not experiments:
        st.info(
            "No results yet. Run the scripts in eval/ (see docs/TESTING.md).",
            icon=":material/info:",
        )
    for e in experiments:
        with st.container(border=True):
            st.markdown(f"#### {e.title}")
            st.markdown(f":gray[Before:] **{e.before}** · :gray[After:] **{e.after}**")
            st.dataframe(table(e), hide_index=True, width="stretch")
            scores = [m for m in e.metrics if m.kind == "score"]
            costs = [m for m in e.metrics if m.kind in ("usd", "seconds") and m.before and m.after]
            left, right = st.columns(2)
            if scores:
                left.caption("QUALITY (HIGHER IS BETTER)")
                left.bar_chart(
                    {m.name: {e.before: m.before, e.after: m.after} for m in scores},
                    horizontal=True,
                )
            if costs and len(costs) >= 1:
                right.caption("COST AND TIME, AFTER AS A MULTIPLE OF BEFORE (LOWER IS BETTER)")
                right.bar_chart({m.name: m.after / m.before for m in costs}, horizontal=True)
            st.markdown(e.reading)
            st.caption(f"Source: {e.source}")
    judge = sorted(RESULTS.glob("judge-*.md"))
    with st.container(border=True):
        st.markdown("#### Judge: agreement with human scores")
        if judge:
            st.markdown(judge[-1].read_text(encoding="utf-8"))
        else:
            st.info(
                "Not run yet. It needs the OpenAI key, and the answer key in "
                "data/is469/judge_labels.jsonl is a draft until the team reviews it.",
                icon=":material/hourglass_empty:",
            )
