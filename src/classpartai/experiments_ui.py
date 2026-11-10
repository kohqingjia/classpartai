"""Experimentation: every comparison the team has run, from the committed results.

The dashboard's third tab. Each experiment is two systems on the same inputs, scored the same way:
agentic RAG against single-pass RAG, the Listener before and after its fixes, the injection screen
before and after widening, the guardrail suite without and with the Auditor agent. A row is read
from ``eval/results/*.json``, never typed in, so the page cannot drift from the results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import altair as alt
import pandas as pd
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
    }.get(kind, f"{value:,.0f}" if abs(value) >= 100 else f"{value:,.2f}".rstrip("0").rstrip("."))


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
        f"On {cfg.get('corpus', 'the course library')} the agent costs "
        f"{many['usd'] / one['usd']:.1f}x as much and takes "
        f"{many['seconds'] / one['seconds']:.1f}x as long per answer. Its verdicts were more "
        "often right, but with 20 answers each one moves a score by about 5 points, so the "
        "accuracy gain is promising, not proven. The stronger case is traceability: an exact "
        "quote behind every verdict, which is worth the cost when a grade follows from it.",
        "eval/results/research-is469-library.json",
    )


EFFORT_RUNS = (
    "research-effort-default.json",
    "research-effort-low.json",
)
EFFORT_COMMANDS = (
    "python eval/research_eval.py --documents var/library/documents.json --max-usd 2 "
    "--name research-effort-default\n"
    "python eval/research_eval.py --documents var/library/documents.json --max-usd 2 "
    "--name research-effort-low --effort low"
)


def research_effort() -> Experiment | None:
    """The Research agent at its default reasoning effort against 'low', same items."""
    runs = [_json(RESULTS / name) for name in EFFORT_RUNS]
    if not all(runs):
        return None
    default, low = (r["agentic"]["summary"] for r in runs if r)
    keys = [
        ("Correct verdicts", "correctness_ok", "higher", "score"),
        ("Context precision", "context_precision", "higher", "score"),
        ("Right passage found", "gold_hit", "higher", "score"),
        ("Quotes are exact", "quoted", "higher", "score"),
        ("Student's mistake identified", "mistake_ok", "higher", "score"),
        ("Tokens per answer", "tokens", "lower", "count"),
        ("Seconds per answer", "seconds", "lower", "seconds"),
        ("Cost per answer", "usd", "lower", "usd"),
    ]
    metrics = [Metric(n, default[k], low[k], b, kind) for n, k, b, kind in keys if k in default]
    return Experiment(
        "Research: reasoning effort",
        "Default effort",
        "Low effort",
        metrics,
        f"Most of Research's output is hidden reasoning. At low effort an answer took "
        f"{low['seconds']:.0f} s instead of {default['seconds']:.0f} s "
        f"({default['seconds'] / low['seconds']:.1f}× faster) and cost "
        f"${low['usd']:.3f} instead of ${default['usd']:.3f}. Correct verdicts went from "
        f"{default['correctness_ok']:.0%} to {low['correctness_ok']:.0%}, context precision "
        f"{default['context_precision']:.0%} to {low['context_precision']:.0%}, and the right "
        f"passage {default['gold_hit']:.0%} to {low['gold_hit']:.0%}. The rise in correct "
        "verdicts is about two answers, so read this as low effort being at least as good and "
        "much cheaper; a larger test set would confirm it. The one drop was in identifying the "
        f"student's specific mistake ({default['mistake_ok']:.0%} to {low['mistake_ok']:.0%}). "
        "It is on with `RESEARCH_REASONING_EFFORT=low`.",
        " and ".join(f"eval/results/{n}" for n in EFFORT_RUNS),
    )


def judge_markdown() -> str | None:
    """The newest Judge-against-people result (eval/judge_eval.py), as a readable table."""
    found = sorted(RESULTS.glob("judge-*.json"))
    d = _json(found[-1]) if found else None
    if not d:
        return None
    agree, cfg = d["summary"]["agreement"], d.get("config", {})

    def cell(value) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    rows = {"All criteria": agree["overall"], **agree["per_criterion"]}
    lines = [
        "| Criterion | Scores compared | Same order | Agreement score | Exact match "
        "| Within 1 point | Average error |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in rows.items():
        lines.append(
            f"| {name.capitalize()} | {s['n']} | {cell(s['spearman'])} | {cell(s['kappa'])} | "
            f"{s['exact']:.0%} | {s['within_one']:.0%} | {cell(s['mae'])} |"
        )
    lines += [
        "",
        f"Model `{cfg.get('model', '?')}`, given the evidence a perfect Research agent would "
        "report. Agreement score: 0 is no better than chance and 1 is identical scores; being "
        "one point off costs less than being three off. Same order: whether the Judge ranks "
        "answers the way the person does. The answer key was written by one person, so this is "
        "agreement with that person.",
    ]
    return "\n".join(lines)


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
    return [e for e in (research(), research_effort(), injection()) if e]


GOOD, BAD, SAME, MUTED = "#5cc2a6", "#ff8f94", "#d4d4d8", "#d4d4d8"


def is_better(m: Metric) -> bool | None:
    if m.before == m.after:
        return None
    return (m.after > m.before) == (m.better == "higher")


def delta_text(m: Metric) -> str:
    """How far the second system is from the first, in the unit the reader thinks in."""
    if m.kind == "score":
        return f"{(m.after - m.before) * 100:+.0f} points"
    if m.before and m.after and not 0.67 < m.after / m.before < 1.5:
        ratio = m.after / m.before
        return f"{ratio:.1f}× the first" if ratio > 1 else f"{1 / ratio:.1f}× lower"
    return f"{m.after - m.before:+,.2f}".rstrip("0").rstrip(".")


def quality_chart(e: Experiment) -> None:
    """Each quality measure as two dots on one 0 to 100% line: where the first system scored and
    where the second did, joined, green when the second is better and red when it is worse. A
    bar would hide that the point is the gap between the two."""
    scores = [m for m in e.metrics if m.kind == "score"]
    if not scores:
        return
    rows = []
    for m in scores:
        better = is_better(m)
        colour = SAME if better is None else GOOD if better else BAD
        rows.append(
            {
                "Measure": m.name,
                "low": min(m.before, m.after),
                "high": max(m.before, m.after),
                "first": m.before,
                "second": m.after,
                "colour": colour,
            }
        )
    frame = pd.DataFrame(rows)
    y = alt.Y(
        "Measure:N",
        sort=[m.name for m in scores],
        title=None,
        axis=alt.Axis(labelLimit=300, labelFontSize=14, labelOverlap=False),
    )
    x = alt.X(
        "low:Q",
        scale=alt.Scale(domain=[0, 1]),
        title="Score",
        axis=alt.Axis(format="%", labelFontSize=13),
    )
    base = alt.Chart(frame)
    line = base.mark_rule(size=4).encode(
        y=y, x=x, x2="high:Q", color=alt.Color("colour:N", scale=None)
    )
    first = base.mark_point(size=160, filled=False, strokeWidth=3, color=MUTED).encode(
        y=y,
        x=alt.X("first:Q"),
        tooltip=[alt.Tooltip("Measure:N"), alt.Tooltip("first:Q", format=".0%", title=e.before)],
    )
    second = base.mark_point(size=190, filled=True, opacity=1).encode(
        y=y,
        x=alt.X("second:Q"),
        color=alt.Color("colour:N", scale=None),
        tooltip=[alt.Tooltip("Measure:N"), alt.Tooltip("second:Q", format=".0%", title=e.after)],
    )
    chart = (
        (line + first + second)
        .properties(height=58 * len(scores) + 30)
        .configure(background="transparent")
        .configure_axis(
            labelColor="#f2f2f4",
            titleColor="#f2f2f4",
            gridColor="#45454b",
            domainColor="#45454b",
            tickColor="#45454b",
        )
        .configure_view(stroke=None)
    )
    st.altair_chart(chart, theme=None, width="stretch")
    st.caption(f"Hollow dot: {e.before}. Filled dot: {e.after}. Green means the second is better.")


def trade_cards(e: Experiment) -> None:
    """Cost, time, tokens and counts as figures with the change beside them, not bars."""
    others = [m for m in e.metrics if m.kind != "score"]
    for start in range(0, len(others), 4):
        cols = st.columns(4)
        for col, m in zip(cols, others[start : start + 4], strict=False):
            better = is_better(m)
            col.metric(
                m.name,
                fmt(m.after, m.kind),
                delta=f"{delta_text(m)} (was {fmt(m.before, m.kind)})",
                delta_color="off" if better is None else "normal" if better else "inverse",
                delta_arrow="off",
            )


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
            st.markdown(f":gray[First:] **{e.before}** · :gray[Second:] **{e.after}**")
            quality_chart(e)
            trade_cards(e)
            with st.expander("Exact numbers"):
                st.dataframe(table(e), hide_index=True, width="stretch")
            st.markdown(e.reading)
            st.caption(f"Source: {e.source}")
    if not research_effort():
        with st.container(border=True):
            st.markdown("#### Research: reasoning effort")
            st.info(
                "Not run yet. It compares Research at its default reasoning effort with `low`, "
                "side by side, on the same labelled items. It needs the OpenAI key and the "
                "course library (Download data, then tools/unpack_download.py). Run both:",
                icon=":material/hourglass_empty:",
            )
            st.code(EFFORT_COMMANDS, language="bash")
    with st.container(border=True):
        st.markdown("#### Judge: agreement with human scores")
        table_md = judge_markdown()
        if table_md:
            st.markdown(table_md)
        else:
            st.info(
                "Not run yet. Run `python eval/judge_eval.py` (needs the OpenAI key).",
                icon=":material/hourglass_empty:",
            )
