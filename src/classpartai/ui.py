"""Animated views of the workflow for the Streamlit app (pure HTML/CSS, no JavaScript).

flow_html()  - the stages, the one the coordinator is using now, and the ones it has used.
board_html() - one card per student showing where their assessment and feedback stand.
"""

from html import escape

STAGES = [
    ("listener", "①", "Transcript", "who said what"),
    ("research", "②", "Evidence", "search the notes"),
    ("judge", "③", "Judge", "score vs rubric"),
    ("auditor", "④", "Auditor", "check the scores"),
    ("feedback", "⑤", "Feedback", "draft per student"),
    ("review", "⑥", "Professor", "approve & send"),
]

# Which stage each coordinator tool works in.
TOOL_STAGE = {
    "inspect_transcript_context": "listener",
    "retrieve_evidence": "research",
    "propose_rubric_assessment": "judge",
    "audit_assessment": "auditor",
    "draft_student_feedback": "feedback",
    "request_professor_review": "review",
}

_BASE_CSS = """
/* Matches the app's dark, Notion-like theme (.streamlit/config.toml). */
:root { --ink:#e3e3e3; --muted:#9b9b9b; --line:#373737; --card:#252525; --bg:#202020;
        --blue:#2383e2; --green:#4dab6f; --amber:#d9a443; --red:#e5605a; }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       color:var(--ink); background:transparent; }
.wrap { background:var(--bg); border:1px solid var(--line); border-radius:12px; padding:14px; }
"""

_FLOW_CSS = """
.banner { font-size:13px; margin:0 0 10px; color:var(--muted); min-height:18px; }
.banner b { color:var(--ink); }
.banner.live b { color:var(--blue); }
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
@keyframes pulse { 0%,100% { box-shadow:0 0 0 0 rgba(35,131,226,.5); }
                   50% { box-shadow:0 0 0 8px rgba(35,131,226,0); } }
.arrow { flex:0 0 22px; height:2px; background:var(--line); position:relative; }
.arrow.live { background:repeating-linear-gradient(90deg,var(--blue) 0 6px,transparent 6px 10px);
              background-size:20px 2px; animation:flow .6s linear infinite; }
.arrow.done { background:var(--green); }
.arrow.both::after { content:"⇄"; position:absolute; top:-10px; left:50%;
                     transform:translateX(-50%); font-size:14px; line-height:1;
                     color:var(--muted); background:var(--bg); padding:0 1px; }
@keyframes flow { from { background-position:0 0; } to { background-position:20px 0; } }
@media (max-width:640px) { .node .what { display:none; } .arrow { flex-basis:8px; }
                           .node .name { font-size:12px; } }
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
    banner: str = "",
) -> str:
    """The workflow strip. ``notes`` puts a short line under a stage; ``banner`` says what the
    coordinator is doing (it may use the stages in any order)."""
    notes = notes or {}
    parts = []
    for i, (key, num, name, what) in enumerate(STAGES):
        if i:
            prev = STAGES[i - 1][0]
            state = "live" if key == active else "done" if key in done and prev in done else ""
            both = " both" if key == "auditor" else ""  # judge and auditor revise each other
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
    live = " live" if active else ""
    head = f'<div class="banner{live}">{banner}</div>' if banner else ""
    return _page(
        _FLOW_CSS, f'<div class="wrap">{head}<div class="flow">{"".join(parts)}</div></div>'
    )


def board_html(cards: list[tuple[str, str, str]], newest: str | None = None) -> str:
    """Student cards: ``cards`` is [(name, state, label)], state being one of waiting /
    commend (green) / encourage (amber) / flagged (red) / summary (blue)."""
    items = []
    for name, state, label in cards:
        new = " new" if name == newest else ""
        items.append(
            f'<div class="card {state}{new}"><div class="who">{escape(name)}</div>'
            f'<div class="state">{escape(label)}</div></div>'
        )
    return _page(_BOARD_CSS, f'<div class="wrap"><div class="board">{"".join(items)}</div></div>')
