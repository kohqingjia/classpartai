"""The Monitoring page: what the agents used and what they did, from the persisted usage ledger.

Two parts: a dashboard (calls, tokens, estimated cost and latency by agent, model and day) and
traces (every step of a workflow run, with the model calls inside it). Everything is read from the
``events`` table (see classpartai/usage.py), so it survives restarts and redeploys.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import altair as alt
import streamlit as st

from classpartai import config, experiments_ui, usage

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


TOKEN_KINDS = ["Input, new", "Input, cached", "Output"]
TOKEN_COLOURS = ["#6aa8e8", "#5cc2a6", "#e8b03c"]  # the app's blue, green and amber inks


def token_chart(groups: list[dict], by_total: bool = True) -> None:
    """Tokens per group as stacked bars: new input, cached input (the cheap part), output
    (which includes hidden reasoning). Every group is labelled, and the chart grows with them."""
    if not groups:
        return
    rows = []
    for g in groups:
        cached = g["cached_tokens"]
        for kind, value in zip(
            TOKEN_KINDS,
            (max(g["input_tokens"] - cached, 0), cached, g["output_tokens"]),
            strict=True,
        ):
            rows.append({"Group": g["group"], "Kind": kind, "Tokens": value})
    order = sorted(
        (g["group"] for g in groups),
        key=(lambda name: -sum(r["Tokens"] for r in rows if r["Group"] == name))
        if by_total
        else (lambda name: name),
    )
    text, grid = "#f2f2f4", "#45454b"
    chart = (
        alt.Chart(alt.Data(values=rows))
        .mark_bar(height=26)
        .encode(
            y=alt.Y(
                "Group:N",
                sort=order,
                title=None,
                axis=alt.Axis(labelLimit=260, labelOverlap=False, labelFontSize=14),
            ),
            x=alt.X("Tokens:Q", title="Tokens", axis=alt.Axis(format="~s", labelFontSize=13)),
            color=alt.Color(
                "Kind:N",
                sort=TOKEN_KINDS,
                scale=alt.Scale(domain=TOKEN_KINDS, range=TOKEN_COLOURS),
                legend=alt.Legend(orient="top", title=None, labelFontSize=14, symbolSize=180),
            ),
            order=alt.Order("Kind:N", sort="ascending"),
            tooltip=["Group:N", "Kind:N", alt.Tooltip("Tokens:Q", format=",")],
        )
        .properties(height=44 * len(groups) + 40)
        .configure(background="transparent")
        .configure_axis(
            labelColor=text, titleColor=text, gridColor=grid, domainColor=grid, tickColor=grid
        )
        .configure_legend(labelColor=text, titleColor=text)
        .configure_view(stroke=None)
    )
    st.altair_chart(chart, theme=None, width="stretch")


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


ICONS = {"run": "🏁", "agent": "🤖", "tool": "🔧", "model": "✨", "embedding": "🧮", "error": "⚠️"}


def node_kind(event: dict) -> str:
    """run, agent, tool, model, embedding or error."""
    return event["detail"].get("span_kind") or event["kind"]


def build_tree(events: list[dict]) -> list[dict]:
    """The run's events as a tree, flattened depth-first: ``{event, depth, children, tokens...}``.

    An event hangs under the span named by its ``detail.parent_id``. One whose parent is missing
    (a run from before spans existed, or a span that never ended) becomes a root, so nothing is
    ever dropped. Each node carries the model calls, tokens and cost of everything beneath it."""
    by_id = {e["detail"]["span_id"]: e for e in events if e["detail"].get("span_id")}
    children: dict[str | None, list[dict]] = {}
    for e in sorted(events, key=lambda e: e["ts"]):
        parent = e["detail"].get("parent_id")
        children.setdefault(parent if parent in by_id else None, []).append(e)

    def rollup(event: dict) -> dict:
        span_id = event["detail"].get("span_id")
        # Only a span can have children: an event with no span ID must not look up ``None``,
        # which is where the roots are filed.
        kids = [rollup(k) for k in children.get(span_id, [])] if span_id else []
        own = event["kind"] in ("model", "embedding")
        return {
            "event": event,
            "children": kids,
            "calls": int(own) + sum(k["calls"] for k in kids),
            "input": (event["input_tokens"] or 0) * own + sum(k["input"] for k in kids),
            "output": (event["output_tokens"] or 0) * own + sum(k["output"] for k in kids),
            "cost": (event["cost_usd"] or 0.0) * own + sum(k["cost"] for k in kids),
            "unpriced": (own and event["cost_usd"] is None) or any(k["unpriced"] for k in kids),
            "failed": event["status"] == "error" or any(k["failed"] for k in kids),
        }

    flat: list[dict] = []

    def walk(node: dict, depth: int) -> None:
        flat.append({**node, "depth": depth})
        for kid in node["children"]:
            walk(kid, depth + 1)

    for root in children.get(None, []):
        walk(rollup(root), 0)
    return flat


def tree_rows(nodes: list[dict]) -> list[dict]:
    if not nodes:
        return []
    start = datetime.fromisoformat(nodes[0]["event"]["ts"])
    longest = max((n["event"]["latency_ms"] or 0 for n in nodes), default=1) or 1
    rows = []
    for n, node in enumerate(nodes, 1):
        e = node["event"]
        kind = node_kind(e)
        rows.append(
            {
                "#": n,
                "Span": "\u2003" * node["depth"] + f"{ICONS.get(kind, '•')} " + step_label(e),
                "Kind": kind,
                "Agent": e["agent"],
                "Starts at": round((datetime.fromisoformat(e["ts"]) - start).total_seconds(), 1),
                "Duration": round((e["latency_ms"] or 0) / longest * 100),
                "Seconds": round((e["latency_ms"] or 0) / 1000, 2),
                "Calls": node["calls"] or None,
                "In": node["input"] or None,
                "Out": node["output"] or None,
                "Cost": None if node["unpriced"] and not node["cost"] else node["cost"] or None,
                "Status": "failed" if node["failed"] and e["status"] != "error" else e["status"],
            }
        )
    return rows


def trace_view(events: list[dict], key: str) -> None:
    """The run's trace: a tree (run, agent, tool, model call) with time, tokens and cost rolled
    up at every level, and any step's input, output and error one click away."""
    if not events:
        st.info(
            "No steps recorded for this run. Runs from before monitoring was added have no trace.",
            icon=":material/info:",
        )
        return
    for e in events:
        if e["status"] == "error":
            st.error(f"{e['agent']} · {step_label(e)}: {e['detail'].get('error', 'failed')}")
    nodes = build_tree(events)
    st.dataframe(
        tree_rows(nodes),
        hide_index=True,
        width="stretch",
        column_config={
            "Starts at": st.column_config.NumberColumn("Starts at (s)", format="%.1f"),
            "Duration": st.column_config.ProgressColumn(
                "Duration", min_value=0, max_value=100, format=" "
            ),
            "Seconds": st.column_config.NumberColumn("Seconds", format="%.2f"),
            "In": st.column_config.NumberColumn("Tokens in", format="%d"),
            "Out": st.column_config.NumberColumn("Tokens out", format="%d"),
            "Cost": st.column_config.NumberColumn("Est. cost", format="$%.5f"),
        },
    )
    st.caption(
        "Indented rows ran inside the row above. Tokens, calls and cost on a run, agent or tool "
        "row include everything inside it. Costs are estimates (see the pricing note)."
    )
    picked = st.selectbox(
        "Inspect a step",
        list(enumerate(nodes, 1)),
        format_func=lambda item: (
            f"{item[0]:02d} · {'  ' * item[1]['depth']}{step_label(item[1]['event'])}"
        ),
        key=f"{key}-inspect",
    )
    inspect(picked[1])


def inspect(node: dict) -> None:
    e = node["event"]
    d = e["detail"]
    kind = node_kind(e)
    st.markdown(
        f"**{ICONS.get(kind, '')} {step_label(e)}** · {kind} · {e['agent']} · {e['status']}"
    )
    cols = st.columns(4)
    cols[0].metric("Took", seconds(e["latency_ms"]))
    cols[1].metric("Model calls", node["calls"])
    cols[2].metric("Tokens in / out", f"{tokens(node['input'])} / {tokens(node['output'])}")
    cols[3].metric("Est. cost", money(node["cost"], not node["unpriced"], node["calls"] or 1))
    if e["kind"] in ("model", "embedding"):
        st.caption(
            f"{e['model']} · {tokens(e['cached_tokens'])} cached input tokens · "
            f"{tokens(e['reasoning_tokens'])} reasoning tokens. The chat API does not return the "
            "model's reasoning text, only how many tokens it spent on it."
        )
    if d.get("error"):
        st.error(d["error"])
    for label, field in (("Input", "input"), ("Output", "output"), ("Arguments", "arguments")):
        if d.get(field):
            st.caption(label.upper())
            st.code(d[field], language=None, wrap_lines=True)
    extra = {
        k: v
        for k, v in d.items()
        if k not in ("input", "output", "arguments", "error", "parent_id", "span_id", "span_kind")
    }
    if extra:
        st.json(extra, expanded=False)


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
        "One place for what the agents used, what they did and how the alternatives compare. "
        "Every model call is recorded with its tokens, time and estimated cost, and kept in the "
        "app's database."
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

    usage_tab, traces_tab, compare_tab = st.tabs(["Usage & cost", "Traces", "Before & after"])
    with usage_tab:
        usage_section(rows)
        other_calls(rows)
    with traces_tab:
        traces_section(records, since, go)
    with compare_tab:
        experiments_ui.render()


def usage_section(rows: list[dict]) -> None:
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
        st.caption("BY AGENT")
        st.dataframe(table_rows(by_agent, "Agent"), hide_index=True, width="stretch")
        st.caption("TOKENS BY AGENT (OUTPUT INCLUDES HIDDEN REASONING)")
        token_chart(by_agent)
        st.caption("BY MODEL")
        st.dataframe(
            table_rows(usage.summarise(rows, "model"), "Model"), hide_index=True, width="stretch"
        )
        by_day = usage.summarise(rows, "day")
        if len(by_day) > 1:
            st.caption("TOKENS PER DAY")
            token_chart(by_day, by_total=False)
        st.caption(
            f"Costs are estimates from {config.MODEL_PRICES.name} (USD per million tokens, edit it "
            "to match your plan), not an invoice: the OpenAI usage page is the source of truth. "
            "A model with no price shows 'no price', never $0. Local models cost nothing."
        )


def traces_section(records, since: str | None, go: Callable[..., None]) -> None:
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


def other_calls(rows: list[dict]) -> None:
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
