"""Animated views of the pipeline for the Streamlit app (pure HTML/CSS, no JavaScript).

flow_html()  - the five stages, which one is working, which are done, which are placeholders.
board_html() - one card per student showing what the Action agent decided for them.
"""

from html import escape

STAGES = [
    ("listener", "①", "Listener", "who said what"),
    ("research", "②", "Research", "find evidence"),
    ("judge", "③", "Judge", "score vs rubric"),
    ("auditor", "④", "Auditor", "check the scores"),
    ("action", "⑤", "Action", "decide & email"),
]

_BASE_CSS = """
:root { --ink:#1f2933; --muted:#6b7785; --line:#d5dbe1; --card:#ffffff; --bg:#f6f8fa;
        --blue:#2563eb; --green:#15803d; --amber:#b45309; --red:#b91c1c; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       color:var(--ink); background:transparent; }
.wrap { background:var(--bg); border:1px solid var(--line); border-radius:12px; padding:14px; }
"""

_FLOW_CSS = """
.flow { display:flex; align-items:center; gap:4px; }
.node { flex:1 1 0; min-width:0; background:var(--card); border:2px solid var(--line);
        border-radius:10px; padding:10px 6px; text-align:center; position:relative;
        transition:border-color .3s, box-shadow .3s; }
.node .num { font-size:18px; line-height:1; color:var(--muted); }
.node .name { font-weight:600; font-size:14px; margin-top:4px; }
.node .what { font-size:11px; color:var(--muted); margin-top:2px; }
.node .note { font-size:11px; margin-top:6px; min-height:14px; color:var(--blue); font-weight:600; }
.node.placeholder { border-style:dashed; }
.node.placeholder .tag { position:absolute; top:-9px; left:50%; transform:translateX(-50%);
        background:var(--bg); color:var(--amber); font-size:9px; font-weight:700;
        letter-spacing:.04em; text-transform:uppercase; padding:0 4px; }
.node.done { border-color:var(--green); }
.node.done .num { color:var(--green); }
.node.done .note { color:var(--green); }
.node.active { border-color:var(--blue); animation:pulse 1.2s ease-in-out infinite; }
.node.active .num { color:var(--blue); }
@keyframes pulse { 0%,100% { box-shadow:0 0 0 0 rgba(37,99,235,.45); }
                   50% { box-shadow:0 0 0 8px rgba(37,99,235,0); } }
.arrow { flex:0 0 22px; height:2px; background:var(--line); position:relative; }
.arrow.live { background:repeating-linear-gradient(90deg,var(--blue) 0 6px,transparent 6px 10px);
              background-size:20px 2px; animation:flow .6s linear infinite; }
.arrow.done { background:var(--green); }
.arrow.both::after { content:"⇄"; position:absolute; top:-10px; left:50%;
                     transform:translateX(-50%); font-size:14px; line-height:1;
                     color:var(--muted); background:var(--bg); padding:0 1px; }
@keyframes flow { from { background-position:0 0; } to { background-position:20px 0; } }
@media (max-width:560px) { .node .what { display:none; } .arrow { flex-basis:10px; } }
"""

_BOARD_CSS = """
.board { display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; }
.card { background:var(--card); border:2px solid var(--line); border-radius:10px; padding:10px; }
.card .who { font-weight:600; font-size:14px; }
.card .state { font-size:12px; margin-top:4px; color:var(--muted); }
.card.waiting .state::after { content:"…"; animation:dots 1.2s steps(3) infinite; }
.card.commend { border-color:var(--green); } .card.commend .state { color:var(--green); }
.card.encourage { border-color:var(--amber); } .card.encourage .state { color:var(--amber); }
.card.flagged { border-color:var(--red); } .card.flagged .state { color:var(--red); }
.card.summary { border-color:var(--blue); } .card.summary .state { color:var(--blue); }
.card.new { animation:pop .45s ease-out; }
@keyframes pop { 0% { transform:scale(.85); opacity:.3; } 70% { transform:scale(1.04); }
                 100% { transform:scale(1); opacity:1; } }
@keyframes dots { 0% { content:""; } 33% { content:"."; } 66% { content:".."; } }
"""


def _page(css: str, body: str) -> str:
    return f"<html><head><style>{_BASE_CSS}{css}</style></head><body>{body}</body></html>"


def flow_html(
    active: str | None = None,
    done: set[str] = frozenset(),
    placeholders: set[str] = frozenset(),
    notes: dict[str, str] | None = None,
) -> str:
    """The pipeline strip. ``notes`` puts a short progress line under a stage."""
    notes = notes or {}
    parts = []
    for i, (key, num, name, what) in enumerate(STAGES):
        if i:
            prev = STAGES[i - 1][0]
            state = "live" if key == active else "done" if key in done and prev in done else ""
            both = " both" if key == "auditor" else ""
            parts.append(f'<div class="arrow {state}{both}"></div>')
        classes = ["node"]
        if key in placeholders:
            classes.append("placeholder")
        classes.append("active" if key == active else "done" if key in done else "")
        mark = "✓" if key in done and key != active else num
        tag = '<span class="tag">placeholder</span>' if key in placeholders else ""
        parts.append(
            f'<div class="{" ".join(classes)}">{tag}<div class="num">{mark}</div>'
            f'<div class="name">{name}</div><div class="what">{what}</div>'
            f'<div class="note">{escape(notes.get(key, ""))}</div></div>'
        )
    return _page(_FLOW_CSS, f'<div class="wrap"><div class="flow">{"".join(parts)}</div></div>')


STATE_LABELS = {
    "waiting": "deciding",
    "commend": "commend email drafted",
    "encourage": "encourage email drafted",
    "flagged": "flagged for review",
    "nothing": "no email needed",
    "summary": "summary sent to prof",
}


def board_html(cards: list[tuple[str, str]], newest: str | None = None) -> str:
    """Decision cards: ``cards`` is [(name, states)], states being space-separated
    STATE_LABELS keys (a student can be emailed and flagged)."""
    items = []
    for name, state in cards:
        new = " new" if name == newest else ""
        label = " · ".join(STATE_LABELS.get(s, s) for s in state.split())
        items.append(
            f'<div class="card {state}{new}"><div class="who">{escape(name)}</div>'
            f'<div class="state">{escape(label)}</div></div>'
        )
    return _page(_BOARD_CSS, f'<div class="wrap"><div class="board">{"".join(items)}</div></div>')
