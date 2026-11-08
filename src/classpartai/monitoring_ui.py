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


TRACE_CSS = """
body { font-size:14px; }
.bar { display:flex; gap:8px; margin:0 0 10px; }
.bar button { background:var(--card); color:var(--ink); border:1px solid var(--line);
  border-radius:6px; padding:5px 10px; font:inherit; cursor:pointer; }
.bar button:hover { border-color:var(--accent); }
.grid { display:grid; align-items:center; gap:10px;
  grid-template-columns:minmax(240px,1fr) 78px 150px 52px 130px 84px 78px; }
.head { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.04em;
  padding:6px 10px; border-bottom:1px solid var(--line); }
.rows { max-height:calc(100vh - 100px); overflow:auto; }
.row { padding:5px 10px; border-bottom:1px solid var(--line); }
.row:hover { background:color-mix(in srgb, var(--ink) 6%, transparent); }
.name { display:flex; align-items:center; gap:6px; min-width:0; }
.name .label { overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.chev { width:20px; height:20px; flex:none; border:0; background:none; color:var(--ink);
  cursor:pointer; font-size:13px; padding:0; border-radius:4px; }
.chev:hover { background:color-mix(in srgb, var(--ink) 14%, transparent); }
.chev.none { cursor:default; visibility:hidden; }
.dot { width:14px; height:14px; border-radius:4px; flex:none; }
.hidden { color:var(--muted); font-size:12px; flex:none; }
.kind { color:var(--muted); }
.dur { display:flex; align-items:center; gap:8px; }
.track { flex:1; height:8px; background:color-mix(in srgb, var(--ink) 10%, transparent);
  border-radius:4px; overflow:hidden; }
.fill { height:100%; background:var(--accent); }
.num { text-align:right; font-variant-numeric:tabular-nums; }
.ok { color:var(--green); } .bad { color:var(--red); } .warn { color:var(--amber); }
"""

TRACE_JS = """
const d=JSON.parse(document.getElementById('data').textContent);
const rows=d.rows, collapsed=new Set(), root=document.getElementById('root');
const COLOUR={run:'#b6b6bd',agent:'#5cc2a6',tool:'#f0c25e',model:'#e8935a',embedding:'#6aa8e8',error:'#ff8f94'};
const el=(t,c,x)=>{const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e;};
const fmt=n=>n==null?'':n.toLocaleString();
function below(i){let c=0;for(let j=i+1;j<rows.length&&rows[j].depth>rows[i].depth;j++)c++;return c;}
function render(){
  root.replaceChildren();
  const bar=el('div','bar');
  const fold=el('button','', 'Collapse agents'), open=el('button','', 'Expand all');
  fold.onclick=()=>{collapsed.clear();rows.forEach((r,i)=>{if(r.hasKids&&r.depth===1)collapsed.add(i);});render();};
  open.onclick=()=>{collapsed.clear();render();};
  bar.append(fold,open);root.append(bar);
  const head=el('div','grid head');
  ['Step','Kind','Duration','Calls','Tokens in / out','Est. cost','Status'].forEach((h,k)=>head.append(el('div',k>2&&k<6?'num':'',h)));
  root.append(head);
  const body=el('div','rows');
  let skip=null;
  rows.forEach((r,i)=>{
    if(skip!==null){if(r.depth>skip)return;skip=null;}
    const row=el('div','grid row');
    const name=el('div','name');name.style.paddingLeft=(r.depth*20)+'px';
    const chev=el('button',r.hasKids?'chev':'chev none',collapsed.has(i)?'▸':'▾');
    if(r.hasKids){chev.title=collapsed.has(i)?'Expand':'Collapse';chev.onclick=()=>{collapsed.has(i)?collapsed.delete(i):collapsed.add(i);render();};}
    const dot=el('span','dot');dot.style.background=COLOUR[r.kind]||'#b6b6bd';
    name.append(chev,dot,el('span','label',r.label));
    if(collapsed.has(i)&&r.hasKids)name.append(el('span','hidden','+'+below(i)+' hidden'));
    row.append(name,el('div','kind',r.kind));
    const dur=el('div','dur'),track=el('div','track'),fill=el('div','fill');
    fill.style.width=r.pct+'%';track.append(fill);
    dur.append(track,el('span','num',r.seconds.toFixed(2)+' s'));
    row.append(dur,el('div','num',r.calls?String(r.calls):''),
      el('div','num',r.input||r.output?fmt(r.input)+' / '+fmt(r.output):''),
      el('div','num',r.cost==null?'':'$'+r.cost.toFixed(5)));
    row.append(el('div',r.status==='ok'?'ok':r.status==='error'||r.status==='failed'?'bad':'warn',r.status));
    body.append(row);
    if(collapsed.has(i)&&r.hasKids)skip=r.depth;
  });
  root.append(body);
}
render();
"""  # noqa: E501


def trace_tree_html(nodes: list[dict]) -> str:
    """The trace as a tree whose own rows fold: an arrow on any step hides everything it ran, so
    the next step after it is in view (like a trace viewer such as Arize Phoenix)."""
    from classpartai.ui import _data_page

    longest = max((n["event"]["latency_ms"] or 0 for n in nodes), default=1) or 1
    rows = []
    for node in nodes:
        e = node["event"]
        ms = e["latency_ms"] or 0
        rows.append(
            {
                "depth": node["depth"],
                "label": step_label(e),
                "kind": node_kind(e),
                "seconds": ms / 1000,
                "pct": round(ms / longest * 100),
                "calls": node["calls"] or 0,
                "input": node["input"] or 0,
                "output": node["output"] or 0,
                "cost": None if node["unpriced"] and not node["cost"] else (node["cost"] or None),
                "status": "failed" if node["failed"] and e["status"] != "error" else e["status"],
                "hasKids": bool(node["children"]),
            }
        )
    return _data_page(TRACE_CSS, {"rows": rows}, TRACE_JS)


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
    st.iframe(trace_tree_html(nodes), height=min(120 + 34 * len(nodes), 640))
    st.caption(
        "Click an arrow to fold a step and everything it ran. Tokens, calls and cost on a run, "
        "agent or tool row include everything inside it. Costs are estimates (see the pricing "
        "note)."
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

    usage_tab, traces_tab, compare_tab = st.tabs(["Usage & cost", "Traces", "Experimentation"])
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
