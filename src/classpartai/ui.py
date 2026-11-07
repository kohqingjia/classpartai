"""Self-contained, text-safe pipeline, student cards and course constellation visuals."""

import json
from pathlib import Path

from classpartai.snippets import AGENTS

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
/* Matches the app's graphite theme (.streamlit/config.toml); amber is the one accent. */
:root { --ink:#ededed; --muted:#a1a1a6; --line:#2a2a2d; --card:#1d1d1f; --bg:#19191b;
        --accent:#e8b03c; --green:#4cc38a; --amber:#e8b03c; --red:#e5484d;
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
a.node:hover, a.node:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.num { color:var(--muted); font:12px ui-monospace,monospace; }
.name { font-weight:600; font-size:12px; margin-top:18px; }
.what,.note { font-size:10px; color:var(--muted); margin-top:7px; }
.active { border-color:var(--accent); box-shadow:inset 0 -3px 0 var(--accent); }
.active .num { color:var(--accent); } .done .num { color:var(--green); }
@media(max-width:700px) { .flow { grid-template-columns:repeat(4,minmax(0,1fr)); }
  .node { padding:8px; } .name { margin-top:6px; } .what { display:none; } }
"""
_BOARD_CSS = """
.board { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:10px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; }
.who { font-weight:600; font-size:14px; }
.state { font-size:12px; margin-top:8px; color:var(--muted); }
.commend .state { color:var(--green); } .encourage .state { color:var(--amber); }
.flagged .state { color:var(--red); }
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


# --- How it works: the whole system on one page, for the presentation -------------------------


def _tools(agent: str) -> list[str]:
    return [t.name for a in AGENTS if a.name == agent for t in a.tools]


# Each node: name, what it does, course topic, kind ("agent" runs its own loop; "model call";
# "pipeline"; "code"; "human"), and an agent's tools (names read from snippets.AGENTS).
SYSTEM_LANES = [
    {
        "step": "Set up",
        "title": "Before class",
        "nodes": [
            [
                "Course library",
                "Slides, readings, labs → one passage per slide or page",
                "",
                "code",
                [],
            ],
            ["Class & voices", "Roster, roles, a voice sample per person", "", "code", []],
        ],
    },
    {
        "step": "① ②",
        "title": "Listener",
        "kind": "pipeline",
        "nodes": [
            [
                "Whisper",
                "Recording → timed text (encoder-decoder transformer)",
                "Topic 2",
                "pipeline",
                [],
            ],
            [
                "Speaker match",
                "pyannote splits by voice; embeddings + cosine similarity name each speaker, "
                "then every line and turn is re-checked",
                "Topics 1, 8",
                "pipeline",
                [],
            ],
            [
                "Who spoke? check",
                "A person confirms the attribution; unknown voices aren't scored",
                "",
                "human",
                [],
            ],
        ],
    },
    {
        "step": "③",
        "title": "Coordinator",
        "kind": "agent",
        "lead": "Agent 1 of 3. Plans the next tool call from what the last one returned, "
        "within a budget. Its tools:",
        "lead_tools": _tools("Coordinator"),
        "badge": "Topic 7",
        "nodes": [
            [
                "Research",
                "Agent 2 of 3, via retrieve_evidence · BM25 + vectors fused with RRF → grade "
                "→ quote",
                "Topic 8",
                "agent",
                _tools("Research"),
            ],
            [
                "Auditor",
                "Agent 3 of 3, via audit_assessment · checks support, citations, injection, "
                "fairness; never changes a score",
                "Topic 6",
                "agent",
                _tools("Auditor"),
            ],
            [
                "Judge",
                "via propose_rubric_assessment · a score per student × criterion, or "
                "'insufficient evidence'",
                "Topic 6",
                "model call",
                [],
            ],
            [
                "Feedback writer",
                "via draft_student_feedback · what went well and one next step, citing turns",
                "Topic 7",
                "model call",
                [],
            ],
        ],
    },
    {
        "step": "④",
        "title": "Professor",
        "nodes": [
            [
                "Approve",
                "Signs off the exact version (SHA-256 of content + recipients)",
                "Topic 9",
                "human",
                [],
            ],
        ],
    },
    {
        "step": "⑤",
        "title": "Delivery",
        "nodes": [
            [
                "AgentMail",
                "Code, not a model, sends the approved emails; test mode redirects",
                "Topic 9",
                "code",
                [],
            ],
        ],
    },
]

SYSTEM_GUARDRAILS = [
    "Transcript and slides are untrusted data, never instructions",
    "Every score must cite the student's own turns",
    "Budgets: 72 model calls · 108 tool calls · 400k tokens · 600 s",
    "No AI can send: a human approves the exact version",
    "Ambiguous sends are never retried automatically",
]

_SYSTEM_CSS = """
.lanes { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.2fr) minmax(0,2.2fr)
         minmax(0,.9fr) minmax(0,.9fr); gap:10px; align-items:stretch; }
.lane { position:relative; background:var(--card); border:1px solid var(--line);
        border-radius:12px; padding:12px; display:flex; flex-direction:column; gap:8px; }
.lane:not(:last-child)::after { content:"→"; position:absolute; right:-13px; top:50%;
        transform:translateY(-50%); color:var(--muted); font-size:14px; }
.head { display:flex; gap:8px; align-items:baseline; }
.step { color:var(--muted); font:12px ui-monospace,monospace; white-space:nowrap; }
.title { font-weight:600; font-size:14px; }
.lead { font-size:11px; color:var(--muted); }
.coord { border-color:#3d3d42; }
.tools { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; }
.node { background:var(--bg); border:1px solid var(--line); border-radius:9px; padding:9px; }
.name { font-weight:600; font-size:12px; }
.what { font-size:11px; color:var(--muted); margin-top:4px; line-height:1.35; }
.badge { display:inline-block; margin-top:6px; font:10px ui-monospace,monospace;
         color:var(--muted); align-self:flex-start; }
.rails { display:flex; flex-wrap:wrap; gap:6px; margin-top:12px; }
.rail { font-size:11px; color:var(--ink); border:1px solid var(--line); background:var(--card);
        border-radius:6px; padding:4px 8px; }
.railhead { font-size:12px; color:var(--muted); margin-top:16px; }
.kind { font:10px ui-monospace,monospace; color:var(--muted); border:1px solid var(--line);
        border-radius:4px; padding:1px 5px; margin-left:auto; white-space:nowrap; }
.kind.agent { color:var(--accent); border-color:color-mix(in srgb,var(--accent) 45%,transparent); }
.nhead { display:flex; gap:6px; align-items:baseline; }
.tl { display:flex; flex-wrap:wrap; gap:4px; margin-top:6px; }
.tn { font:10px ui-monospace,monospace; color:var(--ink); background:var(--card);
      border:1px solid var(--line); border-radius:4px; padding:1px 5px; }
.legend { display:flex; flex-wrap:wrap; gap:14px; font-size:11px; color:var(--muted);
          margin-top:12px; align-items:center; }
@media(max-width:900px) { .lanes { grid-template-columns:1fr; }
  .lane:not(:last-child)::after { content:"↓"; right:auto; left:50%; top:auto; bottom:-15px;
  transform:translateX(-50%); } }
"""


def system_html() -> str:
    """The whole pipeline, from set-up to delivery, with the course topic of each part."""
    return _data_page(
        _SYSTEM_CSS,
        {"lanes": SYSTEM_LANES, "rails": SYSTEM_GUARDRAILS},
        """
const d=JSON.parse(document.getElementById('data').textContent);
const root=document.getElementById('root');root.className='wrap';
const el=(tag,cls,text)=>{const e=document.createElement(tag);e.className=cls;
 if(text!==undefined)e.textContent=text;return e;};
const lanes=el('div','lanes');root.appendChild(lanes);
const KIND={agent:'agent',"model call":'model call',pipeline:'pipeline',code:'code',
 human:'person'};
const toolList=names=>{const t=el('div','tl');names.forEach(n=>t.appendChild(el('span','tn',n)));
 return t;};
d.lanes.forEach(l=>{
 const lane=el('div','lane'+(l.lead?' coord':''));
 const head=el('div','head');head.appendChild(el('span','step',l.step));
 head.appendChild(el('span','title',l.title));
 if(l.kind)head.appendChild(el('span','kind '+(l.kind==='agent'?'agent':''),KIND[l.kind]));
 lane.appendChild(head);
 if(l.lead){lane.appendChild(el('div','lead',l.lead));lane.appendChild(toolList(l.lead_tools));
  lane.appendChild(el('span','badge',l.badge));}
 const box=el('div',l.lead?'tools':'');
 l.nodes.forEach(([name,what,topic,kind,tools])=>{
  const n=el('div','node');const nh=el('div','nhead');nh.appendChild(el('div','name',name));
  // Agents are always labelled, even inside the Coordinator's agent lane.
  if(!l.kind||l.kind!==kind||kind==='agent')
   nh.appendChild(el('span','kind '+(kind==='agent'?'agent':''),KIND[kind]));
  n.appendChild(nh);n.appendChild(el('div','what',what));
  if(tools.length)n.appendChild(toolList(tools));
  if(topic)n.appendChild(el('span','badge',topic));box.appendChild(n);
 });
 lane.appendChild(box);lanes.appendChild(lane);
});
const legend=el('div','legend');
[['agent','agent','runs its own loop: picks a tool, reads the result, picks the next'],
 ['','model call','one structured model call'],['','pipeline','fixed steps, no model deciding'],
 ['','code','plain code'],['','person','a human decision']].forEach(([c,k,t])=>{
 const i=el('span','');i.appendChild(el('span','kind '+c,k));
 i.appendChild(document.createTextNode(' '+t));
 legend.appendChild(i);});
root.appendChild(legend);
root.appendChild(el('div','railhead','Guardrails · Topic 9'));
const rails=el('div','rails');root.appendChild(rails);
d.rails.forEach(r=>rails.appendChild(el('span','rail',r)));
""",
    )
