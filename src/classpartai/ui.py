"""Self-contained, text-safe pipeline, student cards and course constellation visuals."""

import json
from pathlib import Path

STAGES = [
    ("listener", "01", "Listener", "recording → transcript"),
    ("coordinator", "02", "Coordinator", "plan the next action"),
    ("research", "03", "Evidence / Research", "retrieve & verify"),
    ("judge", "04", "Judge", "assess the rubric"),
    ("auditor", "05", "Auditor", "verify first, judge last"),
    ("feedback", "06", "Feedback writer", "a useful next step"),
    ("review", "07", "Delivery", "approve → send"),
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
:root { --ink:#e9edf5; --muted:#9ba6b8; --line:#293140; --card:#151c28; --bg:#10151e;
        --blue:#2383e2; --green:#4dab6f; --amber:#d9a443; --red:#e5605a;
        --ease-out:cubic-bezier(0.23,1,0.32,1); }
* { box-sizing:border-box; }
body { margin:0; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       color:var(--ink); background:transparent; }
.wrap { background:var(--bg); border:1px solid var(--line); border-radius:12px; padding:14px; }
"""

_FLOW_CSS = """
.banner { font-size:12px; margin:0 0 16px; color:var(--muted); }
.flow { display:grid; grid-template-columns:repeat(7,minmax(0,1fr)); gap:8px; }
.node { display:block; text-decoration:none; color:var(--ink); min-width:0;
  background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px 10px; }
a.node:hover, a.node:focus-visible { outline:2px solid #a5b4fc; outline-offset:2px; }
.num { color:#a5b4fc; font:12px ui-monospace,monospace; }
.name { font-weight:600; font-size:12px; margin-top:18px; }
.what,.note { font-size:10px; color:var(--muted); margin-top:7px; }
.active { border-color:#a5b4fc; } .done .num { color:#6ee7b7; }
@media(max-width:700px) { .flow { grid-template-columns:repeat(4,minmax(0,1fr)); }
  .node { padding:8px; } .name { margin-top:6px; } .what { display:none; } }
"""
_BOARD_CSS = """
.board { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
.who { font-weight:600; font-size:14px; }
.state { font-size:12px; margin-top:8px; color:var(--muted); }
.commend .state { color:#6ee7b7; } .encourage .state { color:#fcd68a; }
.flagged .state { color:#fda4af; }
"""


def escaped_json(value) -> str:
    """JSON safe inside a same-origin script element, including mixed-case closing tags."""
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _data_page(css, data, script):
    return _page(
        css,
        '<div id="root"></div><script type="application/json" id="data">'
        + escaped_json(data)
        + "</script><script>"
        + script
        + "</script>",
    )


def _page(css: str, body: str) -> str:
    return f"<html><head><style>{_BASE_CSS}{css}</style></head><body>{body}</body></html>"


def flow_html(
    active=None, done=frozenset(), placeholders=frozenset(), notes=None, banner="", *, links=None
) -> str:
    """Stable, keyboard-accessible pipeline; links open the corresponding agent tab."""
    return _data_page(
        _FLOW_CSS,
        {
            "stages": STAGES,
            "active": active,
            "done": list(done),
            "notes": notes or {},
            "banner": banner,
            "links": links or {},
        },
        """
const d=JSON.parse(document.getElementById('data').textContent);
const root=document.getElementById('root');
const banner=document.createElement('div'); banner.className='banner';
banner.textContent=d.banner; root.appendChild(banner);
const flow=document.createElement('div');flow.className='flow';root.appendChild(flow);
d.stages.forEach(([key,num,name,what])=>{
 const node=document.createElement(d.links[key]?'a':'div');
 node.className='node '+(key===d.active?'active':d.done.includes(key)?'done':'');
 if(d.links[key] && d.links[key].startsWith('?')){
 node.href=d.links[key];node.setAttribute('aria-label','Open '+name);
 node.onclick=event=>{
  const target=Array.from(parent.document.querySelectorAll('[role="tab"]'))
    .find(tab=>tab.textContent.trim()===name);
  if(target){event.preventDefault();target.click();}
 };
 }
 [['num',num],['name',name],['what',what],['note',d.notes[key]||'']].forEach(([cls,text])=>{
  const el=document.createElement('div');el.className=cls;el.textContent=text;node.appendChild(el);
 });flow.appendChild(node);
});
""",
    )


def board_html(cards, newest=None) -> str:
    return _data_page(
        _BOARD_CSS,
        cards,
        """
const root=document.getElementById('root');root.className='board';
JSON.parse(document.getElementById('data').textContent).forEach(([name,state,label])=>{
 const card=document.createElement('div');card.className='card '+state;
 [['who',name],['state',label]].forEach(([cls,text])=>{
  const el=document.createElement('div');el.className=cls;el.textContent=text;card.appendChild(el);
 });root.appendChild(card);
});
""",
    )


# --- The vault: course documents as a constellation, and what the evidence agent retrieved ----

# The page (HTML, CSS and canvas JavaScript) lives in assets/vault.html; Python fills in the data.
_VAULT_PAGE = (Path(__file__).parent / "assets" / "vault.html").read_text()


def _value(obj, key):
    return obj[key] if isinstance(obj, dict) else getattr(obj, key)


def vault_html(
    documents,
    searches=(),
    examined=(),
    cited=(),
    *,
    agent: str = "Evidence agent",
    finished: bool = True,
    running: bool = False,
    start_at: int = 0,
    height: int = 520,
) -> str:
    """The course documents as a constellation (one cluster per file, one star per passage) and
    a replay of what an evidence agent retrieved from them.

    ``searches``: [{"query", "hits": [{"passageId", "score"}]}] (classpartai.retrieval);
    ``examined``: passage IDs the agent graded; ``cited``: the bundle's citations. With
    ``finished`` False the replay stops after the searches (a live run); ``start_at`` skips
    searches already shown. All text is passed as JSON and drawn as text, never as markup.
    """
    docs = []
    for d in documents:
        doc_id, version = _value(d, "id"), _value(d, "version")
        source = _value(d, "source")
        passages = [
            {
                "pid": f"{doc_id}:{version}:{_value(p, 'id')}",
                "page": _value(p, "page"),
                "text": " ".join(_value(p, "text").split())[:260],
            }
            for p in _value(d, "passages")
        ]
        docs.append(
            {
                "title": _value(d, "title"),
                "file": source.split(": ", 1)[-1],
                "passages": passages,
            }
        )
    data = {
        "docs": docs,
        "searches": list(searches),
        "examined": list(examined),
        "cited": [
            {
                "passageId": _value(c, "passageId"),
                "excerpt": _value(c, "excerpt")[:400],
                "relationship": _value(c, "relationship"),
            }
            for c in cited
        ],
        "agent": agent,
        "finished": finished,
        "running": running,
        "startAt": start_at,
    }
    payload = escaped_json(data)
    return (
        _VAULT_PAGE.replace("__DATA__", payload)
        .replace("__STAGE_MOBILE__", str(max(260, height - 200)))
        .replace("__HEIGHT__", str(height))
    )
