"""The Monitoring page: what the agents used and what they did, from the persisted usage ledger.

Two parts: a dashboard (calls, tokens, estimated cost and latency by agent, model and day) and
traces (every step of a workflow run, with the model calls inside it). Everything is read from the
``events`` table (see classpartai/usage.py), so it survives restarts and redeploys.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import streamlit as st

from classpartai import config, usage

SGT = timezone(timedelta(hours=8))
WINDOWS = {"Last 24 hours": 1, "Last 7 days": 7, "Last 30 days": 30, "All time": None}


def local(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(SGT)


def when(ts: str) -> str:
    return local(ts).strftime("%d %b %H:%M")


def money(total: float, priced: bool, calls: int = 1) -> str:
    """A cost for display. A lower bound gets a plus; no price at all says so, never $0."""
    if not calls:
        return "—"
    if not priced and total == 0:
        return "no price"
    return f"${total:,.4f}" + ("" if priced else "+")


def tokens(n: int | None) -> str:
    return "—" if n is None else f"{n:,}"


def seconds(ms: int | None) -> str:
    return "—" if ms is None else f"{ms / 1000:.1f}s"


def step_label(event: dict) -> str:
    called = event["detail"].get("calls")
    if event["kind"] == "model":
        return event["name"] + (f" → {', '.join(called)}" if called else "")
    if event["kind"] == "embedding":
        return f"embed · {event['name']}"
    return event["name"]


# --- A single run's trace ---------------------------------------------------------------------


def trace_table(events: list[dict]) -> list[dict]:
    """One row per step, in the order they started, with when each began and how long it took."""
    if not events:
        return []
    start = local(events[0]["ts"])
    longest = max((e["latency_ms"] or 0 for e in events), default=1) or 1
    return [
        {
            "#": n,
            "Starts at": round((local(e["ts"]) - start).total_seconds(), 1),
            "Agent": e["agent"],
            "Step": step_label(e),
            "Type": {"model": "model call", "tool": "tool", "error": "error"}.get(
                e["kind"], e["kind"]
            ),
            "Took": round((e["latency_ms"] or 0) / longest * 100),
            "Seconds": round((e["latency_ms"] or 0) / 1000, 2),
            "Status": e["status"],
            "In": e["input_tokens"],
            "Out": e["output_tokens"],
            "Cost": e["cost_usd"],
        }
        for n, e in enumerate(events, 1)
    ]


def trace_view(events: list[dict], key: str) -> None:
    if not events:
        st.info(
            "No steps recorded for this run. Runs from before monitoring was added have no trace.",
            icon=":material/info:",
        )
        return
    for e in events:
        if e["status"] == "error":
            st.error(f"{e['agent']} · {step_label(e)}: {e['detail'].get('error', 'failed')}")
    st.dataframe(
        trace_table(events),
        hide_index=True,
        width="stretch",
        column_config={
            "Starts at": st.column_config.NumberColumn("Starts at (s)", format="%.1f"),
            "Took": st.column_config.ProgressColumn(
                "Duration", min_value=0, max_value=100, format="%d"
            ),
            "Seconds": st.column_config.NumberColumn("Seconds", format="%.2f"),
            "In": st.column_config.NumberColumn("Tokens in", format="%d"),
            "Out": st.column_config.NumberColumn("Tokens out", format="%d"),
            "Cost": st.column_config.NumberColumn("Est. cost", format="$%.5f"),
        },
    )
    st.caption(
        "A coordinator step that runs another agent starts before, and lasts as long as, the "
        "model calls inside it. Costs are estimates (see the pricing note on this page)."
    )
    with_detail = [(n, e) for n, e in enumerate(events, 1) if e["detail"]]
    if with_detail:
        picked = st.selectbox(
            "Inspect a step",
            with_detail,
            format_func=lambda item: f"{item[0]:02d} · {item[1]['agent']} · {step_label(item[1])}",
            key=f"{key}-inspect",
        )
        st.json(picked[1]["detail"], expanded=True)


def run_totals(events: list[dict]) -> dict:
    model_calls = [e for e in events if e["kind"] in ("model", "embedding")]
    total = usage.summarise(model_calls)
    total = total[0] if total else None
    first, last = (events[0], events[-1]) if events else (None, None)
    span = (
        (
            datetime.fromisoformat(last["ts"])
            + timedelta(milliseconds=last["latency_ms"] or 0)
            - datetime.fromisoformat(first["ts"])
        ).total_seconds()
        if events
        else 0.0
    )
    return {"total": total, "seconds": span}


def usage_panel(records, run_id: str, key: str) -> None:
    """A compact usage summary and trace for one workflow run (used on the Coordinator tab)."""
    events = records.events(run_id=run_id)
    totals = run_totals(events)
    total = totals["total"]
    cols = st.columns(4)
    cols[0].metric("Model calls", total["calls"] if total else 0)
    cols[1].metric(
        "Tokens in / out",
        f"{tokens(total['input_tokens'])} / {tokens(total['output_tokens'])}" if total else "—",
    )
    cols[2].metric(
        "Est. cost", money(total["cost_usd"], total["priced"], total["calls"]) if total else "—"
    )
    cols[3].metric("Wall time", f"{totals['seconds']:.0f}s" if events else "—")
    trace_view(events, key)


# --- The dashboard ----------------------------------------------------------------------------


def table_rows(groups: list[dict], label: str) -> list[dict]:
    return [
        {
            label: g["group"],
            "Calls": g["calls"],
            "Tokens in": g["input_tokens"],
            "of which cached": g["cached_tokens"],
            "Tokens out": g["output_tokens"],
            "of which reasoning": g["reasoning_tokens"],
            "Est. cost": money(g["cost_usd"], g["priced"], g["calls"]),
            "Avg latency": seconds(g["avg_ms"]),
            "Slowest 5%": seconds(g["p95_ms"]),
            "Errors": g["errors"],
        }
        for g in groups
    ]


def monitoring_view(records, go: Callable[..., None]) -> None:
    st.title("Monitoring")
    st.caption(
        "What the agents used and what they did. Every model call is recorded with its tokens, "
        "time and estimated cost, and kept in the app's database."
    )
    window = st.segmented_control("Period", list(WINDOWS), default="Last 7 days", key="mon-window")
    days = WINDOWS[window or "Last 7 days"]
    since = (
        (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="milliseconds")
        if days
        else None
    )
    rows = records.usage_rows(since)
    for r in rows:
        r["day"] = local(r["ts"]).strftime("%Y-%m-%d")

    st.subheader("Usage")
    overall = usage.summarise(rows)
    if not overall:
        st.info(
            "No model calls recorded in this period. They appear here after an agent runs "
            "(this needs OPENAI_API_KEY).",
            icon=":material/info:",
        )
    else:
        t = overall[0]
        cols = st.columns(5)
        cols[0].metric("Model calls", f"{t['calls']:,}")
        cols[1].metric("Tokens in", tokens(t["input_tokens"]))
        cols[1].caption(f"{tokens(t['cached_tokens'])} cached")
        cols[2].metric("Tokens out", tokens(t["output_tokens"]))
        cols[2].caption(f"{tokens(t['reasoning_tokens'])} reasoning")
        cols[3].metric("Est. cost", money(t["cost_usd"], t["priced"], t["calls"]))
        cols[3].caption("some calls have no price" if not t["priced"] else "from the price table")
        cols[4].metric("Avg latency", seconds(t["avg_ms"]))
        cols[4].caption(f"slowest 5%: {seconds(t['p95_ms'])} · {t['errors']} errors")

        by_agent = usage.summarise(rows, "agent")
        left, right = st.columns([3, 2])
        with left:
            st.caption("BY AGENT")
            st.dataframe(table_rows(by_agent, "Agent"), hide_index=True, width="stretch")
        with right:
            st.caption("TOKENS BY AGENT")
            st.bar_chart(
                {g["group"]: g["input_tokens"] + g["output_tokens"] for g in by_agent},
                horizontal=True,
            )
        st.caption("BY MODEL")
        st.dataframe(
            table_rows(usage.summarise(rows, "model"), "Model"), hide_index=True, width="stretch"
        )
        by_day = usage.summarise(rows, "day")
        if len(by_day) > 1:
            st.caption("TOKENS PER DAY")
            st.bar_chart({g["group"]: g["input_tokens"] + g["output_tokens"] for g in by_day})
        st.caption(
            f"Costs are estimates from {config.MODEL_PRICES.name} (USD per million tokens, edit it "
            "to match your plan), not an invoice: the OpenAI usage page is the source of truth. "
            "A model with no price shows 'no price', never $0. Local models cost nothing."
        )

    st.subheader("Traces")
    runs = records.runs_with_usage(since)
    if not runs:
        st.info(
            "No assessment runs in this period. Start one from a session's Assessment workflow.",
            icon=":material/info:",
        )
    else:
        st.dataframe(
            [
                {
                    "Started": when(r["created_at"]),
                    "Session": r["title"] or "(removed)",
                    "Status": r["status"].replace("_", " "),
                    "Stopped because": (r["stop_reason"] or "").replace("_", " "),
                    "Model": r["manifest"].get("model", "—"),
                    "Calls": r["calls"],
                    "Tokens in": r["input_tokens"],
                    "Tokens out": r["output_tokens"],
                    "Est. cost": money(r["cost_usd"] or 0.0, not r["unpriced"], r["calls"]),
                    "Errors": r["errors"] or 0,
                }
                for r in runs
            ],
            hide_index=True,
            width="stretch",
        )
        picked = st.selectbox(
            "Open a run's trace",
            runs,
            format_func=lambda r: (
                f"{when(r['created_at'])} · {r['title'] or '(removed)'} · {r['status']}"
            ),
            key="mon-run",
        )
        events = records.events(run_id=picked["id"])
        totals = run_totals(events)
        if events and totals["total"]:
            total = totals["total"]
            cols = st.columns(4)
            cols[0].metric("Steps", len(events))
            cols[1].metric("Model calls", total["calls"])
            cols[2].metric("Est. cost", money(total["cost_usd"], total["priced"], total["calls"]))
            cols[3].metric("Wall time", f"{totals['seconds']:.0f}s")
        trace_view(events, "mon")
        if picked["session_id"]:
            st.button(
                "Open this session's agent workspace",
                on_click=go,
                args=("session", picked["session_id"]),
                key="mon-open",
            )

    other = [r for r in rows if not r["run_id"]]
    if other:
        with st.expander(f"Calls outside a workflow run · {len(other)}"):
            st.caption(
                "The Investigate button, session summaries and similar one-off calls. They have "
                "usage but no run to hang a trace on."
            )
            st.dataframe(
                [
                    {
                        "When": when(r["ts"]),
                        "Agent": r["agent"],
                        "Model": r["model"],
                        "Tokens in": r["input_tokens"],
                        "Tokens out": r["output_tokens"],
                        "Est. cost": r["cost_usd"],
                        "Status": r["status"],
                    }
                    for r in other[:200]
                ],
                hide_index=True,
                width="stretch",
                column_config={"Est. cost": st.column_config.NumberColumn(format="$%.5f")},
            )
