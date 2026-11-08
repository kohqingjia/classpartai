"""Streamlit app for ClassPart AI. Run with `uv run streamlit run app.py`.

The workflow follows Le Yong's design (feat/assessment-foundation), ported to Python:
Session (reviewed transcript + roster + rubric + course documents) -> Evidence -> Assessment
(the coordinator agent drafts findings and feedback) -> professor approval of the exact version
-> delivery through AgentMail. Recordings come in through Tina's Listener pipeline.

Pages: Home (a setup checklist), Course library, Class & voices (people, roles and voice
samples), New class session (steps 1-2: record, who spoke?) and the session page (steps 3-5: AI
assessment, approve, send). Voices must be enrolled before a recording can be processed: the
Listener can only name speakers it has a sample for, and unnamed speakers are never scored.
"""

import inspect
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from typing import Any, cast

import streamlit as st
from dotenv import load_dotenv
from groq import Groq
from openai import OpenAI

from classpartai import config, course_map, demo_seminars, exports, reflection_ui, usage
from classpartai import snippets as code_snippets
from classpartai.agent_ui import TABS, overview, render_agent
from classpartai.agents import listener
from classpartai.assessment import AssessmentInputs, parse_inputs
from classpartai.classlist import ClassList
from classpartai.config import DATA_DIR, ENROLLMENT_DIR, REPO_ROOT
from classpartai.evaluation_ui import evaluation_view
from classpartai.evidence import INSTRUCTIONS as EVIDENCE_INSTRUCTIONS
from classpartai.evidence import TOOL_DEFINITIONS as EVIDENCE_TOOLS
from classpartai.evidence import CourseIndex, Investigation, investigate
from classpartai.library import SUPPORTED as LIBRARY_TYPES
from classpartai.library import Library
from classpartai.models import WORKFLOW_LIMITS, configured_driver
from classpartai.monitoring_ui import monitoring_view
from classpartai.participation.coordinator import coordinate
from classpartai.participation.delivery import (
    AgentMailTransport,
    DeliverySettings,
    deliver_approved,
    feedback_email,
)
from classpartai.participation.records import Draft, Records
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import (
    Unprocessable,
    audit_draft,
    observed_count,
    totals,
)
from classpartai.quotes import own_turns, quote_html
from classpartai.research.bridge import session_chunks
from classpartai.research.materials import split_into_chunks
from classpartai.retrieval import examined_of, searches_of
from classpartai.summary.agent import analyse_session
from classpartai.summary.ui import render_session_summary
from classpartai.ui import (
    STAGES,
    TOOL_STAGE,
    board_html,
    flow_html,
    log_plain,
    log_tag,
    log_tool,
    system_html,
    tool_owner,
    vault_html,
)
from classpartai.voices import GOOD_SECONDS, Voices

load_dotenv()  # the Session Summary's API key

DATA = REPO_ROOT / "data"
VIEWS = {
    "home",
    "new",
    "session",
    "summary",
    "library",
    "voices",
    "how",
    "reflection",
    "monitoring",
    "evaluation",
    "downloads",
}
RECORDINGS = DATA_DIR / "recordings"  # class recordings, kept for playback (server volume only)
DEMO_AUDIO = DATA / "demo_audio"
DEMO_SEMINARS = DATA_DIR / "demo-seminars"  # edge-case demos: server only (cloned voices)
# Read aloud for a voice sample: about 20 seconds, with varied sounds.
READING = (
    "Good morning. My name is on the class list, and this is my voice sample for ClassPart AI. "
    "Yesterday I read the slides about retrieval, then tested a quick search over six thick "
    "notebooks. The cheerful zebra jumped over a pile of orange boxes while we argued about "
    "whether agents should search again or stop. Thank you for listening."
)
AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
STAGE_NAMES = {key: name for key, _, name, _ in STAGES}
SGT = timezone(timedelta(hours=8))

# Notion-style touches Streamlit's theme can't express: left-aligned sidebar rows, a big title.
PAGE_CSS = """<style>
[data-testid="stSidebar"] button[data-testid^="stBaseButton"] > div { justify-content:flex-start; }
[data-testid="stSidebar"] button p { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
/* Quiet sidebar: navigation rows 4 apart, section labels closer to their own items. */
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:4px; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { margin:12px 0 0; }
[data-testid="stSidebar"] hr { margin:12px 0; }
/* Session groups are rows, not boxes. */
[data-testid="stSidebar"] [data-testid="stExpander"] details { border:none; background:none; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary { padding:6px 8px; min-height:32px; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary p {
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 { font-weight:600; }
/* Hierarchy from size and colour, not weight. */
h1 { font-size:2.25rem !important; font-weight:600 !important; letter-spacing:-.01em; }
h2, h3 { font-weight:600 !important; }
h4 { font-weight:500 !important; }
.muted { color:#a1a1a6; font-size:.95rem; }
/* Primary action: off-white with dark text; the amber accent is kept for selection. */
button[data-testid="stBaseButton-primary"] {
  background:#ededed; border-color:#ededed; color:#141415; }
button[data-testid="stBaseButton-primary"]:hover {
  background:#ffffff; border-color:#ffffff; color:#141415; }
button[data-testid="stBaseButton-primary"] p { color:#141415; }
/* The current step is marked like a highlighted line in a transcript. */
.st-key-stepbar button[data-testid="stBaseButton-primary"] {
  background:#232325; border-color:#e8b03c; color:#ededed;
  box-shadow:inset 0 -3px 0 #e8b03c; }
.st-key-stepbar button[data-testid="stBaseButton-primary"] p { color:#ededed; }
/* Finished steps are green, so "where am I, what is done" reads at a glance. */
[class*="st-key-stepdone-"] button { border-color:#3fb27f; color:#8fe0b6; }
[class*="st-key-stepdone-"] button p { color:#8fe0b6; }
[class*="st-key-stepdone-"] button:disabled { opacity:1; }
/* The one thing to do now. */
.next-hint { margin:10px 0 4px; padding:10px 14px; border-left:4px solid #e8b03c;
  background:#232325; border-radius:6px; color:#ededed; font-size:1rem; }
.next-hint b { color:#f0c25e; }
/* Captions were too faint on the dark background. */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { color:#b9b9be; }
/* Warnings, errors and successes: stronger bars, so a status is seen before it is read. */
[data-testid="stAlert"] { border-left-width:5px; border-left-style:solid; }
/* Pressable things answer the press. */
button { transition:transform 160ms cubic-bezier(0.23,1,0.32,1),
  background-color 160ms cubic-bezier(0.23,1,0.32,1); }
button:active:not(:disabled) { transform:scale(0.97); }
[data-testid="stCaptionContainer"] { font-variant-numeric:tabular-nums; }
/* Big numbers shrink with the window instead of being cut to "1,92…" */
[data-testid="stMetricValue"] { font-size:clamp(1.35rem, 2.4vw, 2.25rem); }
[data-testid="stMetricValue"] > div { overflow:visible; text-overflow:clip; white-space:normal; }
@media (prefers-reduced-motion:reduce) { button:active:not(:disabled) { transform:none; } }
</style>"""


# --- Shared state -----------------------------------------------------------------------------


@st.cache_resource
def services() -> tuple[Records, ClassList]:
    # A new file: the earlier Action-harness build left a classpartai.db with an incompatible
    # `sessions` table.
    store = Records(DATA_DIR / "assessments.db")
    usage.configure(store.log_event)  # every model call, anywhere in the app, is kept here
    return store, ClassList(DATA_DIR / "classlist.json")


@st.cache_resource
def voices() -> Voices:
    return Voices(ENROLLMENT_DIR)


@st.cache_resource
def course_library() -> Library:
    return Library(DATA_DIR / "library")


def with_library(documents: list) -> list:
    """A new session's documents: its own plus the course library's (at most 100)."""
    own = [d if isinstance(d, dict) else d.model_dump() for d in documents]
    ids = {d["id"] for d in own}
    return (own + [d for d in course_library().documents() if d["id"] not in ids])[:100]


def show_vault(documents, progress: dict | None = None, **options) -> None:
    """The documents as a constellation, replaying what an evidence run retrieved."""
    progress = progress or {}
    bundle = progress.get("bundle") or {}
    height = options.pop("height", 520)
    st.iframe(
        vault_html(
            documents,
            searches_of(progress),
            examined_of(progress),
            bundle.get("citations", []),
            height=height,
            **options,
        ),
        height=height + 4,
    )


@st.cache_resource(show_spinner="Loading speech models (the first run downloads them)…")
def load_listener():
    # The pipeline writes per-speaker clips to a shared folder, so run one recording at a time.
    process_audio, note = listener.load_pipeline()
    return process_audio, note, threading.Lock()


@st.dialog("Delete this session?")
def confirm_delete(session_id: str, title: str) -> None:
    contents = records.session_contents(session_id)
    if contents.pop("emails"):
        st.error("Feedback from this session was emailed to students, so it stays on record.")
        return
    live = live_runs().get(session_id)
    if live and live["ended"] is None:
        st.warning("An assessment is running on this session. Wait for it to finish.")
        return
    st.markdown(f"**{escape(title)}** and everything made from it is deleted for good:")
    lines = [f"- {n} {what}" for what, n in contents.items() if n]
    if recording_of(session_id):
        lines.append("- the class recording")
    st.markdown("\n".join(["- the transcript, roster and rubric", *lines]))
    st.caption("This can't be undone.")
    cancel, delete = st.columns(2)
    if cancel.button("Cancel", width="stretch"):
        st.rerun()
    if delete.button("Delete permanently", type="primary", width="stretch"):
        records.delete_session(session_id)
        (RECORDINGS / f"{session_id}.wav").unlink(missing_ok=True)
        live_runs().pop(session_id, None)
        st.session_state.pop("session_id", None)
        st.query_params.clear()
        st.rerun()


@st.cache_resource
def live_runs() -> dict[str, dict]:
    """Coordinator runs, shared by every browser tab. Each runs in its own thread, so clicking
    around (which restarts this script) or closing the tab doesn't stop it."""
    return {}


def start_run(session_id: str) -> None:
    events: list[tuple[str, dict | None]] = []
    entry = {"events": events, "started": time.monotonic(), "ended": None, "error": None}

    def work() -> None:
        try:
            coordinate(records, session_id, on_event=lambda kind, d: events.append((kind, d)))
        except Exception as exc:  # shown on the page; the run record keeps its stop reason
            entry["error"] = str(exc).splitlines()[0][:300]
        finally:
            entry["ended"] = time.monotonic()

    entry["thread"] = threading.Thread(target=work, name=f"run-{session_id}", daemon=True)
    live_runs()[session_id] = entry
    entry["thread"].start()


def fold_events(events, inputs: AssessmentInputs) -> dict:
    """Where a run has got to, from its events: for the animation and the agent log (live or
    replayed). The banner is plain text: flow_html draws it with textContent."""
    view = {"active": None, "done": set(), "notes": {}, "newest": None, "lines": []}
    view["searches"] = []
    view["banner"] = "Coordinator starting…"
    counts, refused = {}, {}
    for kind, detail in events:
        if kind == "thinking":
            view["active"] = "coordinator"
            view["banner"] = "Coordinator deciding what to do next…"
        elif kind == "substep":
            view["active"] = "research"
            tool = detail["tool"].replace("_", " ")
            view["banner"] = f"Evidence agent step {detail['step']}: {tool}"
            view["lines"].append(
                f"&emsp;↳ {log_tag('Research')} {log_tool(detail['tool'], 'Research')}"
            )
        elif kind == "retrieval":
            view["searches"].append(detail)
            hits = len(detail["hits"])
            view["lines"].append(
                f"&emsp;↳ {log_tag('Research')} retrieved {hits} passage(s) for "
                f"“{log_plain(detail['query'])}”"
            )
        elif kind == "done":
            view["active"] = None
            view["done"].add("coordinator")
            view["banner"] = f"Finished: {detail['stopReason'].replace('_', ' ')}"
        else:
            stage, ok = TOOL_STAGE.get(detail["tool"]), detail["outcome"] == "ok"
            mark = ":green[:material/check:]" if ok else ":red[:material/block:]"
            owner = tool_owner(detail["tool"])
            view["lines"].append(
                f"{mark} {log_tag(owner)} {log_tool(detail['tool'], owner)}: "
                f"{log_plain(detail['summary'])}"
            )
            if stage:
                counts[stage] = counts.get(stage, 0) + 1
                refused[stage] = refused.get(stage, 0) + (not ok)
                note = f"{counts[stage]}×" + (
                    f" ({refused[stage]} refused)" if refused[stage] else ""
                )
                view["notes"][stage] = note
                if ok:
                    view["done"].add(stage)
                view["active"] = stage
                view["banner"] = f"Coordinator chose {STAGE_NAMES[stage]}"
            if detail["tool"] == "draft_student_feedback" and ok:
                sids = json.loads(detail["arguments"]).get("studentIds") or [None]
                view["newest"] = next(
                    (s.displayName for s in inputs.roster if s.id == sids[-1]), None
                )
    return view


def run_panel(session_id: str, inputs: AssessmentInputs) -> None:
    """The animation, student cards and agent log; refreshes itself while a run is going."""
    entry = live_runs().get(session_id)
    running = bool(entry and entry["thread"].is_alive())

    def panel() -> None:
        entry = live_runs().get(session_id)
        alive = bool(entry and entry["thread"].is_alive())
        cards = student_cards(inputs, records.latest_draft(session_id))
        if entry is None:
            show_flow(st.empty(), banner="Coordinator idle")
            show_board(st.empty(), cards)
            return
        view = fold_events(list(entry["events"]), inputs)
        elapsed = int((entry["ended"] or time.monotonic()) - entry["started"])
        # No timer in the banner: changing the iframe's HTML every tick would reload it and
        # restart its animation. The clock is in the caption below.
        show_flow(st.empty(), view["active"], view["done"], view["notes"], view["banner"])
        show_board(st.empty(), cards, view["newest"])
        if alive and (view["searches"] or view["active"] == "research"):
            st.caption("Live retrieval from the course documents")
            show_vault(
                inputs.documents,
                {"searches": view["searches"]},
                finished=False,
                running=view["active"] == "research",
                start_at=max(0, len(view["searches"]) - 1),
                height=420,
            )
        runs = records.runs(session_id)
        if runs:
            p, limits = runs[0]["progress"], WORKFLOW_LIMITS
            st.caption(
                f"⏱ {elapsed} s of {limits['seconds']} · {p.get('modelCalls', 0)} of "
                f"{limits['modelCalls']} model calls · {p.get('tokens', 0) // 1000}k of "
                f"{limits['tokens'] // 1000}k tokens"
                + (" · keeps running if you leave this page" if alive else "")
            )
        with st.expander("Agent log", expanded=alive):
            with st.container(height=240, border=False):
                st.markdown("  \n".join(view["lines"]) or "Starting…", unsafe_allow_html=True)
        if entry["error"]:
            st.error(entry["error"])
        if not alive and not entry.get("reported"):
            entry["reported"] = True
            st.rerun()  # the whole page, to show the new draft

    st.fragment(run_every=2 if running else None)(panel)()


# --- Replay: a stored run, event by event, with no model calls --------------------------------

REPLAY_SPEEDS = {"Step": None, "1×": 1, "5×": 5, "20×": 20}


def replay_key(session_id: str) -> str:
    return f"replay-{session_id}"


def open_replay(session_id: str, run_id: str) -> None:
    events = [(e["at"], e["kind"], e["detail"]) for e in records.run_events(run_id)]
    st.session_state[replay_key(session_id)] = {
        "run": run_id,
        "events": events,
        "pos": 0,
        "clock": 0.0,
        "wall": 0.0,
        "playing": False,
    }


def replay_control(session_id: str, action: str) -> None:
    """The replay buttons' callbacks: they only move its position (nothing is written)."""
    state = st.session_state.get(replay_key(session_id))
    if state is None:
        return
    events, n = state["events"], len(state["events"])
    if action == "close":
        st.session_state.pop(replay_key(session_id), None)
    elif action == "next":
        state.update(playing=False, pos=min(n, state["pos"] + 1))
        state["clock"] = events[state["pos"] - 1][0] if state["pos"] else 0.0
    elif action == "restart":
        state.update(playing=False, pos=0, clock=0.0)
    elif action == "end":
        state.update(playing=False, pos=n, clock=events[-1][0] if events else 0.0)
    elif action == "play":
        if state["pos"] >= n:
            state.update(pos=0, clock=0.0)
        state.update(playing=True, wall=time.monotonic())
    elif action == "pause":
        state["playing"] = False


def replay_section(session_id: str, inputs: AssessmentInputs) -> tuple[bool, Draft | None]:
    """Offer to replay a stored run. Returns (open and unfinished, the run's final draft once
    its replay has finished, else None).

    Read-only: it reads the run's stored events and drafts, and calls no model, tool,
    retrieval or email."""
    runs = records.replayable_runs(session_id)
    state = st.session_state.get(replay_key(session_id))
    if state and not any(r["id"] == state["run"] for r in runs):
        st.session_state.pop(replay_key(session_id), None)
        state = None
    if not runs:
        if records.runs(session_id):
            st.caption("This session's run was recorded before replays were kept.")
        return False, None
    if state is None:
        labels = {
            r["id"]: f"Run at {when(r['created_at'])} · "
            + (r["stop_reason"] or "finished").replace("_", " ")
            for r in runs
        }
        col_play, col_pick, _ = st.columns([1, 1, 2])
        run_id = (
            runs[0]["id"]
            if len(runs) == 1
            else col_pick.selectbox(
                "Run to replay",
                list(labels),
                format_func=lambda key: labels[key],
                label_visibility="collapsed",
                key=f"replay-pick-{session_id}",
            )
        )
        col_play.button(
            "▶ Replay this run",
            width="stretch",
            on_click=open_replay,
            args=(session_id, run_id),
            help="Plays a past run's stored events at presentation speed. No AI calls.",
        )
        return False, None

    run = next(r for r in runs if r["id"] == state["run"])
    st.info(
        f"Replay of the run at {when(run['created_at'])}: no AI calls are made.",
        icon=":material/replay:",
    )
    speed = st.radio(
        "Speed",
        list(REPLAY_SPEEDS),
        horizontal=True,
        key=f"replay-speed-{session_id}",
        help="Step: one event per click (best for presenting). The others compress the run's "
        "real timing.",
    )
    if REPLAY_SPEEDS[speed] is None:
        state["playing"] = False
    n, playing = len(state["events"]), state["playing"]
    cols = st.columns(5)
    cols[0].button(
        "⏭ Next event",
        on_click=replay_control,
        args=(session_id, "next"),
        disabled=state["pos"] >= n,
        width="stretch",
    )
    cols[1].button(
        "⏸ Pause" if playing else "▶ Play",
        on_click=replay_control,
        args=(session_id, "pause" if playing else "play"),
        disabled=REPLAY_SPEEDS[speed] is None,
        width="stretch",
    )
    cols[2].button(
        "⏮ Restart", on_click=replay_control, args=(session_id, "restart"), width="stretch"
    )
    cols[3].button(
        "⏩ Skip to end", on_click=replay_control, args=(session_id, "end"), width="stretch"
    )
    cols[4].button(
        "Close replay",
        icon=":material/close:",
        on_click=replay_control,
        args=(session_id, "close"),
        width="stretch",
    )

    def view() -> None:
        state = st.session_state.get(replay_key(session_id))
        if state is None:
            return
        events, n = state["events"], len(state["events"])
        if state["playing"]:
            now = time.monotonic()
            state["clock"] += (now - state["wall"]) * (REPLAY_SPEEDS[speed] or 1)
            state["wall"] = now
            state["pos"] = sum(1 for at, _, _ in events if at <= state["clock"])
        shown = events[: state["pos"]]
        finished = state["pos"] >= n
        fold = fold_events([(kind, detail) for _, kind, detail in shown], inputs)
        if not shown:
            fold["banner"] = "Replay ready: press Next event or Play"
        draft = replay_draft(shown, run["progress"].get("latestDraftId") if finished else None)
        show_flow(st.empty(), fold["active"], fold["done"], fold["notes"], fold["banner"])
        show_board(st.empty(), student_cards(inputs, draft), fold["newest"])
        if not finished and (fold["searches"] or fold["active"] == "research"):
            st.caption("Retrieval from the course documents, as it happened")
            show_vault(
                inputs.documents,
                {"searches": fold["searches"]},
                finished=False,
                running=fold["active"] == "research",
                start_at=max(0, len(fold["searches"]) - 1),
                height=420,
            )
        recorded = events[-1][0] if events else 0.0
        progress = run["progress"]
        st.caption(
            f"⏱ {min(state['clock'], recorded):.0f} s of {recorded:.0f} s recorded · "
            f"event {state['pos']} of {n}"
            + (
                f" · the run used {progress.get('modelCalls', 0)} model calls and "
                f"{progress.get('tokens', 0) // 1000}k tokens"
                if finished
                else ""
            )
        )
        with st.expander("Agent log", expanded=True):
            with st.container(height=240, border=False):
                st.markdown("  \n".join(fold["lines"]) or "Nothing yet.", unsafe_allow_html=True)
        if finished:
            reason = (run["stop_reason"] or "finished").replace("_", " ")
            st.success(
                f"Replay finished ({reason}): draft version {draft.version}, as the run left it."
                if draft
                else f"Replay finished ({reason}): the run left no draft."
            )
        if state["playing"] and finished:
            state["playing"] = False
            st.rerun()  # the whole page: stop ticking and show the stored draft

    st.fragment(run_every=1 if state["playing"] else None)(view)()
    if state["pos"] < n:
        return True, None
    return False, replay_draft(state["events"], run["progress"].get("latestDraftId"))


def replay_draft(events: list, recorded: str | None = None) -> Draft | None:
    """The draft as of these events: the run's recorded latest if given, else the last draft
    an action made."""
    draft_id = recorded or next(
        (d["draftId"] for _, k, d in reversed(events) if k == "action" and d.get("draftId")),
        None,
    )
    return records.draft(draft_id) if draft_id else None


def file_to_wav(src: Path, dest: Path) -> Path:
    """Any audio file as 16 kHz mono 16-bit WAV, the format the speech models expect."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src)]
    subprocess.run([*cmd, "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(dest)], check=True)
    return dest


def to_wav(upload, dest: Path) -> Path:
    """An uploaded or recorded clip (Streamlit UploadedFile) as 16 kHz mono WAV."""
    suffix = Path(getattr(upload, "name", "") or "clip.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix) as src:
        src.write(upload.getbuffer())
        src.flush()
        return file_to_wav(Path(src.name), dest)


def recording_of(session_id: str) -> Path | None:
    path = RECORDINGS / f"{session_id}.wav"
    return path if path.exists() else None


def seek(key: str, seconds: float) -> None:
    st.session_state[key] = seconds
    st.session_state[f"{key}-play"] = True


def recording_player(path: Path, key: str) -> None:
    """The recording, starting wherever a transcript line's ▶ last pointed."""
    autoplay = st.session_state.pop(f"{key}-play", False)
    start = st.session_state.get(key, 0)
    st.audio(str(path), start_time=start, autoplay=autoplay)
    if start:
        st.caption(f"Playing from {int(start) // 60}:{int(start) % 60:02d}")


STEPS = ["Record", "Who spoke?", "AI assessment", "Approve", "Send"]
# The agents (or person) at work in each step, so the step bar doubles as the pipeline.
STEP_AGENTS = {
    1: "Listener · Whisper transcribes",
    2: "Listener · voice match",
    3: "Coordinator → Research → Judge → Auditor → Feedback writer",
    4: "Professor · human approval gate",
    5: "Delivery · AgentMail",
}
# What the person should do at each step, in plain words (shown under the step bar).
STEP_NOW = {
    1: "record or upload the class audio, then press Transcribe.",
    2: "check who said what (▶ plays anything unsure), tick the box, then Create session.",
    3: "press Generate assessment and wait. The agents prepare a draft; nothing is sent.",
    4: "read each student's email, then approve this exact version.",
    5: "press Send; accepted emails are never sent twice.",
}
STEP_PARAMS = {name: n for n, name in enumerate(STEPS, start=1)}  # ?step=<name>


def step_bar(view: str, current: int, done: set[int], reachable: set[int]) -> None:
    """The five steps, each naming its agents; reachable steps are buttons (1-based)."""
    with st.container(key="stepbar"):
        for n, col in enumerate(st.columns(len(STEPS)), start=1):
            finished = n in done and n != current
            mark = "✓" if finished else str(n)
            with col, st.container(key=f"step{'done' if finished else 'todo'}-{n}"):
                st.button(
                    f"{mark} · {STEPS[n - 1]}",
                    key=f"stepbar-{n}",
                    width="stretch",
                    type="primary" if n == current else "secondary",
                    disabled=n not in reachable,
                    on_click=go,
                    args=(view, st.session_state.session_id if view == "session" else None, n),
                )
                st.caption(STEP_AGENTS[n])
    hint = STEP_NOW[current]
    live = live_runs().get(st.session_state.get("session_id") or "")
    if view == "session" and current == 3 and live and not live["ended"]:
        hint = "the agents are working. This page updates as they go; nothing is sent."
    st.markdown(f'<div class="next-hint"><b>Now:</b> {hint}</div>', unsafe_allow_html=True)
    if current > 1 and current - 1 in reachable:
        st.button(
            f"← Back to {STEPS[current - 2]}",
            key="step-back",
            type="tertiary",
            on_click=go,
            args=(view, st.session_state.session_id if view == "session" else None, current - 1),
        )


def who_spoke(turns, names: dict[str, str], audio: Path | None, player_key: str) -> None:
    """Step 2: how many lines each kind of speaker has, the recording and the transcript."""
    prof_turns = sum(t.speaker.kind == "professor" for t in turns)
    unknown = sum(t.speaker.kind == "uncertain" for t in turns)
    per_student = dict.fromkeys(names, 0)
    for t in turns:
        if t.speaker.kind == "student" and t.speaker.studentId in per_student:
            per_student[t.speaker.studentId] += 1
    cols = st.columns(4)
    cols[0].metric("Lines", len(turns))
    cols[1].metric("Professor", prof_turns)
    cols[2].metric("Students", sum(per_student.values()))
    cols[3].metric("Unknown (not scored)", unknown)
    silent = [names[sid] for sid, n in per_student.items() if n == 0]
    if silent:
        st.caption(
            "Not heard in this recording (they'll get 'No observed contribution'): "
            + ", ".join(silent)
        )
    attacks = [t for t in turns if t.injection == "suspected_instruction"]
    if attacks:
        st.warning(
            f"The Listener flagged {len(attacks)} line(s) that seem to give the grader "
            "instructions (" + ", ".join(t.id for t in attacks) + "). The words stay in the "
            "transcript and are scored on their content only; the Judge and Auditor are told."
        )
    if audio and audio.exists():
        recording_player(audio, player_key)
    show_transcript(turns, names, player_key=player_key if audio and audio.exists() else None)


def clock(stamp: datetime) -> str:
    """'3:50 PM'. Not strftime's %-I: Windows doesn't support it."""
    return f"{stamp.hour % 12 or 12}:{stamp:%M %p}"


def when(iso: str) -> str:
    """'Wed 29 Oct, 3:50 PM' in Singapore time."""
    stamp = datetime.fromisoformat(iso).astimezone(SGT)
    return f"{stamp:%a} {stamp.day} {stamp:%b}, {clock(stamp)}"


def default_title() -> str:
    now = datetime.now(SGT)
    return f"Seminar, {now:%a} {now.day} {now:%b} {clock(now)}"


def go(view: str, session: str | None = None, step: int | None = None) -> None:
    """Navigate by changing the address: each change is a browser history entry, so the
    browser's back and forward buttons walk through pages and steps."""
    params = {"view": view}
    if session:
        params["session"] = session
        st.session_state.session_id = session
    # Always record the step, so a history entry can't be reinterpreted after the session moves on.
    if step is None and view == "new":
        step = 1
    elif step is None and view == "session" and session:
        step = default_step(session)
    if step:
        params["step"] = STEPS[step - 1]
    st.query_params.from_dict(params)  # one change, so one history entry
    st.session_state.view = view


def default_step(session: str) -> int:
    """The first step still to do: ③ until there's a draft, ④ until approved, then ⑤."""
    latest = records.latest_draft(session)
    if latest is None:
        return 3
    return 5 if records.active_approval(session) else 4


def show_flow(slot, active=None, done=(), notes=None, banner="") -> None:
    with slot.container():
        # flow_html passes everything as escaped JSON and draws it with textContent: no markup.
        st.iframe(flow_html(active, frozenset(done), frozenset(), notes or {}, banner), height=165)


def show_board(slot, cards, newest=None) -> None:
    with slot.container():
        rows = -(-len(cards) // 4)
        st.iframe(board_html(cards, newest), height=40 + 72 * max(rows, 1))


def student_cards(inputs: AssessmentInputs, draft) -> list[tuple[str, str, str]]:
    """Where each student's assessment stands in a draft."""
    cards = []
    for s in inputs.roster:
        if draft is None:
            cards.append((s.displayName, "waiting", "waiting"))
            continue
        content = draft.content
        flagged = any(
            i.studentId == s.id and i.id.startswith("model:") and i.disposition == "open"
            for i in content.audit.issues
        )
        has_feedback = any(f.studentId == s.id for f in content.feedback)
        total = totals(content, inputs, s.id)
        score = (
            f"{total['total']:g}/{total['maximum']}"
            if total["total"] is not None
            else f"{total['assessedCriteria']}/{total['totalCriteria']} criteria scored"
        )
        label = f"{score} · {'feedback drafted' if has_feedback else 'no feedback yet'}"
        if flagged:
            cards.append((s.displayName, "flagged", label + " · auditor flag"))
        elif has_feedback and total["total"] is not None:
            cards.append((s.displayName, "commend", label))
        elif has_feedback:
            cards.append((s.displayName, "encourage", label))
        else:
            cards.append((s.displayName, "waiting", label))
    return cards


def speaker_name(inputs: AssessmentInputs, turn) -> str:
    sp = turn.speaker
    if sp.kind == "student":
        return next(s.displayName for s in inputs.roster if s.id == sp.studentId)
    return f"{sp.label} ({sp.kind})"


def show_transcript(turns, names: dict[str, str], player_key: str | None = None) -> None:
    """The transcript as a conversation. Uncertain turns are greyed out: they are never scored.
    With ``player_key``, each line has a ▶ that plays the recording from that moment."""
    for t in turns:
        sp = t.speaker
        stamp = f"{t.startMs // 60000}:{t.startMs // 1000 % 60:02d}"
        if sp.kind == "student":
            who, avatar = names.get(sp.studentId) or sp.studentId, ":material/person:"
        elif sp.kind == "professor":
            who, avatar = sp.label, ":material/school:"
        else:
            who, avatar = f"{sp.label} · speaker uncertain", ":material/help:"
        with st.chat_message(who, avatar=avatar):
            if player_key:
                col_who, col_play = st.columns([12, 1])
                col_who.caption(f"**{who}** · {stamp} · {t.id}")
                col_play.button(
                    "▶",
                    key=f"{player_key}-{t.id}",
                    help=f"Play from {stamp}",
                    type="tertiary",
                    on_click=seek,
                    args=(player_key, t.startMs / 1000),
                )
            else:
                st.caption(f"**{who}** · {stamp} · {t.id}")
            if sp.kind == "uncertain":
                st.markdown(f":gray[{t.text}]  \n:orange[Unknown speaker · won't be scored]")
            else:
                st.markdown(t.text)


def set_recipients_from_classlist(session_id: str, inputs: AssessmentInputs) -> int:
    count = 0
    for s in inputs.roster:
        student = classlist.get(s.id)
        if student:
            records.set_recipient(session_id, s.id, student.email)
            count += 1
    return count


def citation_text(bundles, ref) -> str:
    bundle = bundles.get(ref.evidenceRunId)
    cite = (
        next((x for x in bundle.citations if x.passageId == ref.passageId), None)
        if bundle
        else None
    )
    if cite is None:
        return "> Citation unavailable; review required"
    return f"> {cite.excerpt}\n\n— {cite.title}, p. {cite.page}"


records, classlist = services()

st.set_page_config(page_title="ClassPart AI", page_icon=":material/school:", layout="wide")
st.html(PAGE_CSS)

# --- Sidebar ----------------------------------------------------------------------------------

sessions = records.sessions()
by_id = {s["id"]: s for s in sessions}
if st.session_state.get("session_id") not in by_id:
    st.session_state.session_id = next(iter(by_id), None)
# The address is the source of truth for where we are (see go()).
linked = st.query_params.get("session")
if linked in by_id:
    st.session_state.session_id = linked
st.session_state.view = st.query_params.get("view") or ("session" if linked in by_id else "home")
if st.session_state.view not in VIEWS or (
    st.session_state.view in {"session", "summary"} and not sessions
):
    st.session_state.view = "home"
requested_step = STEP_PARAMS.get(st.query_params.get("step", ""))


def nav(
    label: str,
    view_name: str,
    session: str | None = None,
    key: str | None = None,
    icon: str | None = None,
) -> None:
    selected = st.session_state.view == view_name and (
        session is None or session == st.session_state.session_id
    )
    st.button(
        label,
        key=key,
        icon=icon,
        width="stretch",
        type="secondary" if selected else "tertiary",
        on_click=go,
        args=(view_name, session),
    )


with st.sidebar:
    st.markdown("### ClassPart AI")
    nav("Home", "home", icon=":material/home:")
    nav("New class session", "new", icon=":material/mic:")
    st.caption("Class sessions")
    for s in sessions:
        with st.expander(
            s["title"],
            icon=":material/description:",
            expanded=(
                s["id"] == st.session_state.session_id
                and st.session_state.view in {"session", "summary"}
            ),
        ):
            nav(
                "Assessment",
                "session",
                s["id"],
                key=f"assessment-{s['id']}",
                icon=":material/fact_check:",
            )

            nav(
                "Summary",
                "summary",
                s["id"],
                key=f"summary-{s['id']}",
                icon=":material/notes:",
            )
    if not sessions:
        st.caption("No sessions yet.")
    st.divider()
    st.caption("Set up")
    nav("Course library", "library", icon=":material/library_books:")
    nav("Class & voices", "voices", icon=":material/group:")
    st.caption("Present")
    nav("How it works", "how", icon=":material/account_tree:")
    nav("Reflection & risks", "reflection", icon=":material/lightbulb:")
    nav("Monitoring", "monitoring", icon=":material/monitoring:")
    nav("Evaluation", "evaluation", icon=":material/balance:")
    nav("Download data", "downloads", icon=":material/download:")
    if os.getenv("EMAIL_TEST_MODE", "true").lower() != "false":
        recipient = os.getenv("EMAIL_TEST_RECIPIENT", "(not set)")
        st.caption(f"Test mode: every email goes to {recipient}")
    if not os.getenv("OPENAI_API_KEY"):
        st.warning("No OPENAI_API_KEY: agent runs will be blocked.")

view = st.session_state.view
session_id = cast(str, st.session_state.session_id)  # None only on pages that do not use it
people = classlist.all()
registry = voices().registry()
voiced_profs = [p for p in classlist.professors() if p.person_id in registry]
voiced_students = [p for p in classlist.students() if p.person_id in registry]
ready_to_record = bool(voiced_profs and voiced_students)


def open_session(new_inputs: AssessmentInputs, recipients: dict[str, str] | None = None) -> str:
    new_id = records.create_session(new_inputs)
    if recipients is None:
        n = set_recipients_from_classlist(new_id, new_inputs)
    else:
        for sid, email in recipients.items():
            records.set_recipient(new_id, sid, email)
        n = len(recipients)
    go("session", new_id)
    st.toast(f"Session created; {n} recipient(s) set.")
    return new_id


def demo_people() -> list[dict]:
    return json.loads((DEMO_AUDIO / "manifest.json").read_text(encoding="utf-8"))["people"]


def enrol_seminar_voices() -> None:
    """The demo seminars' synthetic voices (their professor), marked as demo entries."""
    for person in demo_seminars.voices(DEMO_SEMINARS):
        if not voices().get(person["personId"]):
            voices().enrol(person["personId"], person["name"], Path(person["path"]), demo=True)


# The chunk size Research really uses, read from its signature so this page can't drift.
_CHUNKING = inspect.signature(session_chunks).parameters
CHUNK_WINDOW, CHUNK_OVERLAP = _CHUNKING["window"].default, _CHUNKING["overlap"].default
PASSAGE_UNIT = {".pptx": "Slide", ".pdf": "Page", ".ipynb": "Cells", ".docx": "Section"}


def show_passages(entry: dict) -> None:
    """One library file as Research sees it: a passage per slide, page or group of cells, cut
    into the overlapping word windows that get embedded at the first search."""
    doc, unit = entry["document"], PASSAGE_UNIT.get(Path(entry["file"]).suffix.lower(), "Part")
    window, overlap = CHUNK_WINDOW, CHUNK_OVERLAP
    rows = [
        {
            unit: p.get("page") or n,
            "Words": len(p["text"].split()),
            "Chunks": len(split_into_chunks(p["text"], window, overlap)),
            "Starts with": " ".join(p["text"].split()[:14]) + "…",
        }
        for n, p in enumerate(doc["passages"], start=1)
    ]
    st.caption(
        f"Uploading makes one passage per {unit.lower()}. Nothing is embedded yet: at a "
        f"session's first search each passage is cut into windows of {window} words that "
        f"overlap by {overlap}, and each window is embedded and indexed for BM25. A citation "
        f"names the passage and window, e.g. `{doc['id']}:{doc['passages'][0]['id']}#0`."
    )
    st.dataframe(rows, hide_index=True, width="stretch", height=min(36 * len(rows) + 38, 280))
    labels = [f"{unit} {r[unit]} · {r['Words']} words" for r in rows]
    pick = st.selectbox("Open a passage", labels, key=f"passage-{entry['file']}")
    passage = doc["passages"][labels.index(pick)]
    col_text, col_chunks = st.columns(2)
    col_text.markdown("**The passage**")
    col_text.text(passage["text"])
    col_chunks.markdown(f"**Its chunks** ({window} words, {overlap} overlap)")
    pieces = split_into_chunks(passage["text"], window, overlap)
    for n, piece in enumerate(pieces):
        words = piece.split()
        shared = " ".join(words[:overlap]) if n else ""
        rest = " ".join(words[overlap:]) if n else piece
        col_chunks.caption(f"#{n} · {len(words)} words")
        col_chunks.markdown(
            (f":orange-background[{shared}] " if shared else "") + rest.replace("$", "\\$")
        )
    if len(pieces) > 1:
        col_chunks.caption("Highlighted: the words a chunk shares with the one before it")


def show_script(script: dict, player_key: str | None) -> None:
    """A demo seminar's script: what was actually said, to check the Listener against."""
    st.markdown("**What was said** · the script this demo recording was made from")
    st.caption(script["case"])
    for n, line in enumerate(script["lines"]):
        stamp = f"{int(line['start']) // 60}:{int(line['start']) % 60:02d}"
        col_line, col_play = st.columns([12, 1])
        col_line.markdown(f"`{stamp}` **{line['speaker']}**: {line['text']}")
        if player_key:
            col_play.button(
                "▶",
                key=f"{player_key}-script-{n}",
                help=f"Play from {stamp}",
                type="tertiary",
                on_click=seek,
                args=(player_key, line["start"]),
            )


def turn_label(turn) -> str:
    words = turn.text.split()
    return f"{turn.id} · " + " ".join(words[:10]) + ("…" if len(words) > 10 else "")


def draft_form(latest, inputs) -> dict:
    """The draft as a form, a tab per student: each criterion's result, score, reason and the
    turns it rests on, then their feedback. Citations and limitations are kept as they are.
    Returns the edited draft as a dict, for the same validation as any other version."""
    criteria = {c.id: c for c in inputs.rubric.criteria}
    turns = {t.id: t for t in inputs.transcript.turns}
    key = f"form-{latest.id}"
    findings, feedback = [], []
    tabs = st.tabs([s.displayName for s in inputs.roster])
    for student, tab in zip(inputs.roster, tabs, strict=True):
        with tab:
            own = [
                t.id
                for t in inputs.transcript.turns
                if t.speaker.kind == "student" and t.speaker.studentId == student.id
            ]
            for f in [x for x in latest.content.findings if x.studentId == student.id]:
                c, k = criteria.get(f.criterionId), f"{key}-{student.id}-{f.criterionId}"
                low, high = (c.minScore, c.maxScore) if c else (0, 100)
                with st.container(border=True):
                    st.markdown(f"**{c.title if c else f.criterionId}**")
                    result = st.radio(
                        "Result",
                        ["Scored", "Not enough evidence"],
                        index=0 if f.status == "scored" else 1,
                        horizontal=True,
                        key=f"{k}-status",
                    )
                    score = None
                    if result == "Scored":
                        start = f.score if f.score is not None else low
                        score = st.number_input(
                            f"Score ({low} to {high})",
                            min_value=float(low),
                            max_value=float(high),
                            value=float(min(max(start, low), high)),
                            step=0.5,
                            key=f"{k}-score",
                        )
                    why = st.text_area("Why", f.justification, key=f"{k}-why")
                    picked = st.multiselect(
                        "Based on",
                        list(dict.fromkeys([*own, *f.turnIds])),
                        default=f.turnIds,
                        format_func=lambda tid: turn_label(turns[tid]) if tid in turns else tid,
                        key=f"{k}-turns",
                    )
                    kept = [f"{len(f.citations)} course citation(s)"] if f.citations else []
                    kept += [f"limitation: {x}" for x in f.limitations]
                    if kept:
                        st.caption("Kept as they are: " + "; ".join(kept))
                findings.append(
                    {
                        **f.model_dump(),
                        "status": "scored" if result == "Scored" else "insufficient_evidence",
                        "score": score,
                        "justification": why,
                        "turnIds": picked,
                    }
                )
            fb = next((x for x in latest.content.feedback if x.studentId == student.id), None)
            if fb:
                st.markdown("**Feedback to the student**")
                k = f"{key}-{student.id}-feedback"
                feedback.append(
                    {
                        **fb.model_dump(),
                        "strengths": st.text_area("What went well", fb.strengths, key=f"{k}-s"),
                        "nextStep": st.text_area("Next step", fb.nextStep, key=f"{k}-n"),
                    }
                )
    # Findings and feedback for anyone not on the roster stay exactly as they were.
    roster = {s.id for s in inputs.roster}
    findings += [f.model_dump() for f in latest.content.findings if f.studentId not in roster]
    feedback += [f.model_dump() for f in latest.content.feedback if f.studentId not in roster]
    return {"findings": findings, "feedback": feedback}


def enrol_demo_voices() -> None:
    """The synthetic voices of the demo recording, marked as demo entries."""
    with tempfile.TemporaryDirectory() as tmp:
        for person in demo_people():
            if voices().get(person["personId"]):
                continue
            wav = file_to_wav(DEMO_AUDIO / person["file"], Path(tmp) / f"{person['personId']}.wav")
            voices().enrol(person["personId"], person["name"], wav, demo=True)


def transcribe(wav: Path, roster: list[dict], professors: set[str], meta: dict) -> None:
    """Run the Listener on a 16 kHz WAV and keep the result for step 2 (Who spoke?)."""
    voices().ensure()
    process_audio, note, lock = load_listener()
    with lock, st.spinner("Transcribing and identifying speakers…"):
        result = process_audio(str(wav))
    ids = {r["displayName"]: r["id"] for r in roster}
    st.session_state.pending = {
        "diagnostics": json.loads(json.dumps({**result, "note": note}, default=str)),
        "transcript": listener.to_transcript(result, ids, "review-1", professors),
        "roster": roster,
        "audio": str(wav),
        "note": note,
        **meta,
    }


def generate_summary_json(system_prompt, user_prompt):
    """Groq (Tina's setup) when GROQ_API_KEY is set, otherwise the app's OpenAI model."""
    messages: list[Any] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    groq = bool(os.getenv("GROQ_API_KEY"))
    provider, model = ("groq", "openai/gpt-oss-20b") if groq else ("openai", config.OPENAI_MODEL)
    with usage.tracking(agent="summary", session_id=st.session_state.get("session_id")):
        started = usage.begin()
        try:
            if groq:
                response = Groq(api_key=os.environ["GROQ_API_KEY"]).chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0,
                )
            else:
                # gpt-5 models only accept the default temperature.
                response = OpenAI().chat.completions.create(
                    model=model,
                    messages=messages,
                    response_format={"type": "json_object"},
                )
        except Exception as error:
            usage.record_model_call(
                started,
                model=model,
                provider=provider,
                status="error",
                error=f"{type(error).__name__}: {error}",
            )
            raise
        usage.record_model_call(
            started, model=model, provider=provider, usage=getattr(response, "usage", None)
        )
    content = response.choices[0].message.content
    if content is None:
        raise ValueError("The model returned no text")
    return json.loads(content)


# --- Home -------------------------------------------------------------------------------------

if view == "home":
    st.title("ClassPart AI")
    st.markdown(
        '<p class="muted">Record a seminar, let the agents check what was said against the '
        "course notes and score it against the rubric, then approve and send each student "
        "their feedback.</p>",
        unsafe_allow_html=True,
    )
    entries = course_library().entries()
    students = classlist.students()
    with st.container(border=True):
        st.markdown("**Set up** · do these once per course")
        rows = [
            (
                bool(entries),
                "Course library",
                f"{len(entries)} {'file' if len(entries) == 1 else 'files'} · "
                f"{sum(len(e['document']['passages']) for e in entries)} passages"
                if entries
                else "Upload the slides the evidence agent should search",
                "library",
            ),
            (
                ready_to_record,
                "Class & voices",
                f"{len(students)} students · voice samples for {len(voiced_students)} of "
                f"{len(students)} and {len(voiced_profs)} "
                f"{'professor' if len(voiced_profs) == 1 else 'professors'}",
                "voices",
            ),
        ]
        for ok, name, detail, target in rows:
            col_state, col_name, col_go = st.columns([6, 1, 1])
            mark = ":green[:material/check_circle:]" if ok else ":orange[:material/error:]"
            col_state.markdown(f"{mark} **{name}** · :gray[{detail}]")
            col_go.button("Open", key=f"home-{target}", on_click=go, args=(target,))
        mail = os.getenv("EMAIL_TEST_RECIPIENT", "")
        test_mode = os.getenv("EMAIL_TEST_MODE", "true").lower() != "false"
        st.markdown(
            ":green[:material/check_circle:] **Email** · :gray["
            + (f"test mode: every email goes to {mail}" if test_mode else "sends to students")
            + "]"
        )
        if not ready_to_record:
            st.caption(
                "Recording unlocks once the professor and at least one student have a voice "
                "sample: the Listener can only name people it has heard before."
            )
    col_new, col_demo, _ = st.columns([1, 1, 2])
    col_new.button(
        "New class session",
        icon=":material/mic:",
        type="primary",
        width="stretch",
        on_click=go,
        args=("new",),
    )
    col_demo.button(
        "Try the demo recording",
        icon=":material/play_arrow:",
        width="stretch",
        on_click=go,
        args=("new",),
    )
    if sessions:
        st.markdown("#### Recent sessions")
        for s in sessions[:6]:
            col_title, col_when = st.columns([4, 1], vertical_alignment="center")
            col_title.button(
                s["title"],
                icon=":material/description:",
                key=f"home-open-{s['id']}",
                type="tertiary",
                on_click=go,
                args=("session", s["id"]),
            )
            col_when.caption(when(s["created_at"]))

# --- New class session: steps 1 (Record) and 2 (Who spoke?) -----------------------------------

elif view == "new":
    pending = st.session_state.get("pending")
    new_step = 2 if pending and (requested_step or 2) == 2 else 1
    step_bar("new", new_step, {1} if pending else set(), {1, 2} if pending else {1})
    st.session_state.setdefault("new-title", default_title())
    st.title(st.session_state["new-title"] or "Untitled session")
    col_title, col_course = st.columns(2)
    title = col_title.text_input("Title", key="new-title")
    course = col_course.text_input("Course", "IS469 Gen AI with LLMs")

    if new_step == 1 or pending is None:  # step 2 only exists once a recording was processed
        if pending:
            st.info(
                "An unsaved transcript is waiting in ② Who spoke?. Transcribing a new recording "
                "replaces it."
            )
        with st.container(border=True):
            st.markdown("**① Record the seminar**")
            names = [f"{p.name} (professor)" for p in voiced_profs] + [
                p.name for p in voiced_students
            ]
            missing = [p.name for p in classlist.students() if p.person_id not in registry]
            st.caption(
                ("Will recognise: " + ", ".join(names) if names else "Nobody is enrolled yet.")
                + (
                    f" · No voice sample (won't be recognised): {', '.join(missing)}"
                    if missing
                    else ""
                )
            )
            if not ready_to_record:
                st.warning(
                    "Enrol the professor's and at least one student's voice first: the Listener "
                    "can only name people it has a sample for, and unnamed speakers aren't scored."
                )
                st.button(
                    "Go to Class & voices", icon=":material/group:", on_click=go, args=("voices",)
                )
            col_rec, col_up = st.columns(2)
            recorded = col_rec.audio_input(
                "Record in the browser", key="mic", disabled=not ready_to_record
            )
            uploaded = col_up.file_uploader(
                "…or upload a recording", type=AUDIO_TYPES, disabled=not ready_to_record
            )
            audio = recorded or uploaded
            st.caption(
                "By recording, you confirm everyone being recorded has agreed to it. The "
                "recording is kept on this server so you can play it back."
            )
            if st.button("Transcribe →", type="primary", disabled=not (audio and ready_to_record)):
                wav = RECORDINGS / f"pending-{uuid.uuid4().hex}.wav"
                roster = [{"id": p.person_id, "displayName": p.name} for p in classlist.students()]
                try:
                    to_wav(audio, wav)
                    transcribe(
                        wav,
                        roster,
                        {p.name for p in classlist.professors()},
                        {"title": title, "course": course, "demo": False},
                    )
                    go("new", step=2)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Couldn't process the recording ({str(exc).splitlines()[0][:300]}).")

        with st.container(border=True):
            st.markdown("**No recording to hand?**")
            col_rec_demo, col_seminar, col_week7, col_fixture = st.columns(4)
            if col_rec_demo.button(
                "▶ Use the demo recording",
                width="stretch",
                help="A 48-second mock seminar read by synthetic voices, with their voice samples",
            ):
                wav = RECORDINGS / f"pending-{uuid.uuid4().hex}.wav"
                sample = parse_inputs((DATA / "sample_assessment.json").read_text(encoding="utf-8"))
                try:
                    with st.spinner("Enrolling the demo voices…"):
                        enrol_demo_voices()
                    file_to_wav(DEMO_AUDIO / "seminar.ogg", wav)
                    profs = {p["name"] for p in demo_people() if p["role"] == "professor"}
                    transcribe(
                        wav,
                        [r.model_dump() for r in sample.roster],
                        profs,
                        {
                            "title": sample.sessionTitle.replace("(sample)", "(demo recording)"),
                            "course": sample.courseTitle,
                            "demo": True,
                        },
                    )
                    go("new", step=2)
                    st.rerun()
                except Exception as exc:
                    st.error(
                        f"Couldn't process the demo recording ({str(exc).splitlines()[0][:300]})."
                    )
            if col_seminar.button(
                "Skip to the demo transcript",
                width="stretch",
                help="The same seminar as a ready-made transcript: starts at step 3",
            ):
                demo = parse_inputs((DATA / "sample_assessment.json").read_text(encoding="utf-8"))
                sample_people = json.loads(
                    (DATA / "sample_classlist.json").read_text(encoding="utf-8")
                )
                open_session(
                    AssessmentInputs.model_validate(
                        {**demo.model_dump(), "documents": with_library(demo.documents)}
                    ),
                    {pid: e["email"] for pid, e in sample_people.items()},
                )
                st.rerun()
            if col_week7.button(
                "IS469 Week 7 seminar",
                width="stretch",
                help="Tasmin's transcript of the Week 7 (Agentic AI) Q&A, checked against "
                "the course library: starts at step 3",
            ):
                # The slides come from the course library: they are the instructor's, not ours to
                # commit.
                seminar = json.loads(
                    (DATA / "is469" / "week7_seminar.json").read_text(encoding="utf-8")
                )
                documents = with_library([])
                if documents:
                    seminar["documents"] = documents
                    open_session(AssessmentInputs.model_validate(seminar))
                    st.rerun()
                st.warning("Upload the IS469 slides in Course library first.")
            if col_fixture.button("Le Yong's fixture", width="stretch"):
                open_session(
                    parse_inputs((DATA / "fixture-fictional.json").read_text(encoding="utf-8"))
                )
                st.rerun()
            with st.expander("Import a session file (JSON)"):
                upload = st.file_uploader("Session JSON", type=["json"])
                if upload and st.button("Import", type="primary"):
                    try:
                        open_session(parse_inputs(upload.getvalue().decode()))
                        st.rerun()
                    except ValueError as exc:
                        st.error(str(exc))
            demos = demo_seminars.available(DEMO_SEMINARS)
            if demos:
                with st.expander(
                    f"Demo seminars: {len(demos)} edge cases, with their scripts",
                    icon=":material/theater_comedy:",
                ):
                    st.caption(
                        "Mock classes in our cloned voices, with a synthetic professor. Each runs "
                        "through the real Listener; the script is kept so you can check it."
                    )
                    for demo in demos:
                        col_text, col_go = st.columns([4, 1])
                        col_text.markdown(f"**{demo['title']}**  \n{demo['case']}")
                        if col_go.button("Transcribe →", key=f"demo-seminar-{demo['id']}"):
                            wav = RECORDINGS / f"pending-{uuid.uuid4().hex}.wav"
                            try:
                                with st.spinner("Enrolling the demo professor's voice…"):
                                    enrol_seminar_voices()
                                file_to_wav(Path(demo["audio"]), wav)
                                profs = {p.name for p in classlist.professors()} | {
                                    v["name"]
                                    for v in demo_seminars.voices(DEMO_SEMINARS)
                                    if v["role"] == "professor"
                                }
                                transcribe(
                                    wav,
                                    [
                                        {"id": p.person_id, "displayName": p.name}
                                        for p in classlist.students()
                                    ],
                                    profs,
                                    {
                                        "title": demo["title"],
                                        "course": course,
                                        "demo": False,
                                        "script": {k: demo[k] for k in ("id", "case", "lines")},
                                    },
                                )
                                go("new", step=2)
                                st.rerun()
                            except Exception as exc:
                                st.error(
                                    f"Couldn't process {demo['title']} "
                                    f"({str(exc).splitlines()[0][:300]})."
                                )
    else:
        transcript = pending["transcript"]
        roster = pending["roster"]
        names = {r["id"]: r["displayName"] for r in roster}
        with st.container(border=True):
            st.markdown("**② Who spoke?** Check the AI's attribution before anything is scored.")
            if pending.get("note"):
                st.info(pending["note"])
            turns = transcript.turns
            audio = Path(pending["audio"]) if pending.get("audio") else None
            who_spoke(turns, names, audio, "pending-seek")
            if pending.get("script"):
                show_script(pending["script"], "pending-seek" if audio else None)
            confirmed = st.checkbox("I've checked who said what (listen with ▶ if unsure)")
            col_go, col_drop, _ = st.columns([1, 1, 2])
            if col_go.button("Create session →", type="primary", disabled=not confirmed):
                demo = pending.get("demo")
                sample = parse_inputs((DATA / "sample_assessment.json").read_text(encoding="utf-8"))
                documents = (
                    with_library(sample.documents)
                    if demo
                    else course_library().documents()
                    or json.loads(config.COURSE_DOCUMENTS.read_text(encoding="utf-8"))
                )
                new_inputs = AssessmentInputs.model_validate(
                    {
                        "formatVersion": 1,
                        "provenance": "reviewed",
                        "courseTitle": pending["course"] if not demo else sample.courseTitle,
                        "sessionTitle": pending["title"],
                        "roster": roster,
                        "transcript": transcript,
                        "rubric": sample.rubric.model_dump()
                        if demo
                        else json.loads((DATA / "default_rubric.json").read_text(encoding="utf-8")),
                        "documents": documents,
                    }
                )
                recipients = None
                if demo:
                    sample_people = json.loads(
                        (DATA / "sample_classlist.json").read_text(encoding="utf-8")
                    )
                    recipients = {pid: e["email"] for pid, e in sample_people.items()}
                new_id = open_session(new_inputs, recipients)
                RECORDINGS.mkdir(parents=True, exist_ok=True)
                shutil.move(pending["audio"], RECORDINGS / f"{new_id}.wav")
                diagnostics = pending.get("diagnostics") or {}
                if pending.get("script"):
                    diagnostics = {**diagnostics, "script": pending["script"]}
                records.save_listener_run(new_id, diagnostics)
                del st.session_state["pending"]
                st.rerun()
            if col_drop.button("Discard and record again"):
                Path(pending["audio"]).unlink(missing_ok=True)
                del st.session_state["pending"]
                go("new", step=1)
                st.rerun()

# --- Course library ---------------------------------------------------------------------------

elif view == "library":
    library = course_library()
    st.title("Course library")
    st.write(
        "Upload the course's slides, readings and labs. Every slide or page becomes a passage "
        "the evidence agents can search and quote; new class sessions use everything here."
    )
    st.session_state.setdefault("upload-round", 0)
    with st.container(border=True):
        uploads = st.file_uploader(
            "⬆ Upload files",
            type=[t.lstrip(".") for t in LIBRARY_TYPES],
            accept_multiple_files=True,
            key=f"library-upload-{st.session_state['upload-round']}",
        )
        if uploads and st.button(f"Add {len(uploads)} file(s) to the library", type="primary"):
            added = []
            with st.spinner("Reading the files…"):
                for upload in uploads:
                    try:
                        doc = library.add(upload.name, upload.getvalue())
                        added.append(f"{doc['title']} ({len(doc['passages'])} passages)")
                    except ValueError as exc:
                        st.error(str(exc))
            if added:
                st.session_state["upload-round"] += 1
                st.toast("Added " + ", ".join(added))
                st.rerun()
        st.caption(
            "PDF, PowerPoint, Markdown, text or notebooks · up to 50 MB each · stored on this "
            "server only (course material is licensed). Re-uploading a file name replaces it."
        )
    entries = library.entries()
    if entries:
        show_vault([e["document"] for e in entries], agent="Course library", height=460)
        for entry in entries:
            doc = entry["document"]
            with st.container(border=True):
                col_name, col_count, col_when, col_remove = st.columns(
                    [4, 2, 2, 1], vertical_alignment="center"
                )
                col_name.markdown(f"**{doc['title']}**  \n:gray[{entry['file']}]")
                col_count.write(f"{len(doc['passages'])} passages")
                col_when.caption(when(entry["uploadedAt"]))
                if col_remove.button("Remove", key=f"lib-rm-{entry['file']}"):
                    library.remove(entry["file"])
                    st.rerun()
                with st.expander("See its passages and how they're chunked"):
                    show_passages(entry)
        st.caption(
            "Sessions keep the documents they were created with, so removing a file here "
            "doesn't change past evidence or scores."
        )
    else:
        st.info("No files yet. Upload the slides for the topics your seminars cover.")

# --- Class & voices ---------------------------------------------------------------------------

elif view == "voices":
    st.title("Class & voices")
    st.write(
        "Everyone who speaks in a seminar needs a voice sample, including the professor: the "
        "Listener names speakers by comparing them with these samples, and anyone it can't name "
        "isn't scored. Only enrol people who have agreed to it."
    )

    def voice_input(key: str):
        """Record (reading the paragraph) or upload a voice sample; returns the clip or None."""
        st.markdown(f"> {READING}")
        col_rec, col_up = st.columns(2)
        recorded = col_rec.audio_input("Read the paragraph above", key=f"{key}-rec")
        uploaded = col_up.file_uploader(
            "…or upload a clip of them speaking alone", type=AUDIO_TYPES, key=f"{key}-up"
        )
        return recorded or uploaded

    def save_voice(person, clip) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                check = voices().enrol(
                    person.person_id, person.name, to_wav(clip, Path(tmp) / "voice.wav")
                )
            except ValueError as exc:
                st.error(f"{person.name}: {exc}")
                return False
        tip = "" if check.seconds >= GOOD_SECONDS else " (20 s or more recognises people better)"
        st.toast(f"Saved {person.name}'s voice: {check.seconds:.0f} s{tip}")
        return True

    with st.container(border=True):
        st.markdown("**Add a person**")
        st.session_state.setdefault("person-round", 0)
        round_key = f"person-{st.session_state['person-round']}"
        col_name, col_mail, col_role = st.columns([2, 3, 1])
        name = col_name.text_input("Name", key=f"{round_key}-name")
        email_address = col_mail.text_input("Email", key=f"{round_key}-email")
        role = col_role.radio("Role", ["student", "professor"], key=f"{round_key}-role")
        clip = voice_input(round_key)
        if st.button("Add", type="primary"):
            if not name.strip() or "@" not in email_address:
                st.error("Enter a name and a valid email.")
            else:
                person = classlist.upsert(name, email_address, role=role)
                if clip is None or save_voice(person, clip):
                    st.session_state["person-round"] += 1
                    st.rerun()

    everyone = sorted(people.values(), key=lambda p: (p.role != "professor", p.name))
    if everyone:
        st.markdown(f"#### {len(everyone)} people")
    for person in everyone:
        entry = registry.get(person.person_id)
        with st.container(border=True):
            col_who, col_voice, col_remove = st.columns([3, 4, 1])
            badge = "Professor" if person.role == "professor" else "Student"
            col_who.markdown(f"**{person.name}** · {badge}  \n:gray[{person.email}]")
            if entry:
                seconds = voices().seconds(person.person_id) or 0
                col_voice.caption(f"Voice sample · {seconds:.0f} s")
                col_voice.audio(str(voices().clip_path(person.person_id)))
            else:
                col_voice.markdown(
                    ":orange[:material/warning: No voice sample: won't be recognised]"
                )
            if col_remove.button("Remove", key=f"rm-{person.person_id}"):
                classlist.remove(person.person_id)
                voices().remove(person.person_id)
                st.rerun()
            with st.expander("Record a new voice sample" if entry else "Add a voice sample"):
                clip = voice_input(f"re-{person.person_id}")
                if st.button("Save voice sample", key=f"save-voice-{person.person_id}"):
                    if clip is None:
                        st.error("Record or upload a clip first.")
                    elif save_voice(person, clip):
                        st.rerun()

    demo_voices = [pid for pid, e in registry.items() if e.get("demo")]
    if demo_voices:
        col_demo, col_clear = st.columns([4, 1])
        col_demo.caption(
            f"Also enrolled: {len(demo_voices)} synthetic voices from the demo recording. They "
            "don't count as class members."
        )
        if col_clear.button("Remove demo voices"):
            for pid in demo_voices:
                voices().remove(pid)
            st.rerun()

# --- How it works: the whole system on one page, for the presentation --------------------------

elif view == "how":
    st.title("How ClassPart AI works")
    st.markdown(
        '<p class="muted">A professor records a seminar. Agents turn it into a transcript, check '
        "what each student said against the course notes, score it against the rubric and "
        "draft feedback. The professor approves the exact version before any student sees "
        "it.</p>",
        unsafe_allow_html=True,
    )
    st.iframe(system_html(), height=860)

    st.subheader("The five steps")
    st.markdown(
        "| Step | Who does the work | What comes out |\n"
        "|---|---|---|\n"
        "| ① Record | **Listener**: Whisper turns speech into timed text | A transcript |\n"
        "| ② Who spoke? | **Listener**: each line's voice is matched to an enrolled sample; "
        "a person checks it | Lines attributed to students, the professor or *unknown* |\n"
        "| ③ AI assessment | **Coordinator** calls Research, Judge, Auditor and Feedback writer "
        "as tools | Scores with citations, audit issues, draft feedback |\n"
        "| ④ Approve | **The professor** reviews issues and approves one exact version | "
        "An approval tied to a fingerprint of that version |\n"
        "| ⑤ Send | **Delivery** (plain code) emails the approved feedback | One email per "
        "student, with its delivery state |"
    )
    st.caption(
        "Every run's events are stored with their timing, so ③ can replay a past run (▶ Replay "
        "this run) for a presentation: same visuals, no AI calls, nothing written."
    )

    st.subheader("Why it's agentic")
    st.markdown(
        "- **The Coordinator plans.** No fixed script: it reads each tool's result and picks the "
        "next call (inspect the transcript, retrieve evidence, propose scores, audit, draft "
        "feedback, request review). A refused call comes back with the reason, and it adapts.\n"
        "- **Research is agentic RAG.** It writes its own queries, searches with BM25 and "
        "vectors fused by Reciprocal Rank Fusion, grades what it finds, searches again if the "
        "evidence is weak, and only cites exact excerpts from the course notes.\n"
        "- **The Judge is an agent too.** It starts with the rubric, each student's own turns and "
        "a summary of Research's evidence, scores many students per call with a confidence, and "
        "fetches more turns or a full evidence bundle only when it needs them. It flags what the "
        "professor should check, and a revision after the audit re-scores only the students the "
        "Auditor raised.\n"
        "- **Verify first, judge last.** Every score the Judge saves must pass deterministic "
        "validation (right students, cited turns that exist); a student who breaks a rule is "
        "refused with the reason. Then the Auditor checks support, attribution and uncertainty "
        "before anything reaches the professor.\n"
        "- **Bounded.** Every run has a budget (96 model calls, 108 tool calls, 500k tokens, "
        "900 s) and stops cleanly when it runs out.\n"
        "- **Watched.** Every model call's tokens, time and estimated cost, and every step of "
        "every run, are recorded (Saurabh's usage ledger). The **Monitoring** page shows them."
    )

    st.subheader("The agents and their tools")
    st.markdown(
        "Four parts are **agents**: a model in a loop that picks a tool, reads what it "
        "returned and picks the next, until it's done. The Coordinator runs the other three "
        "by calling a tool (*agents as tools*). In the diagram each agent has its own colour, "
        "and so do its tools. The rest are single model calls, "
        "fixed pipelines or plain code, on purpose: sending email, for one, is never left to "
        "a model."
    )
    kinds = {
        "agent": "Agent (its own loop)",
        "model call": "One model call",
        "pipeline": "Fixed pipeline",
        "code": "Plain code",
    }
    st.markdown(
        "| Part | What it is | Started by | Tools | Who built it |\n|---|---|---|---|---|\n"
        + "\n".join(
            f"| **{a.name}** | {kinds[a.kind]} | {a.called_by} | "
            f"{len(a.tools) or '—'} | {a.owner} |"
            for a in code_snippets.AGENTS
        )
    )
    for agent in code_snippets.AGENTS:
        st.markdown(f"#### {agent.name}")
        st.caption(f"{kinds[agent.kind]} · started by {agent.called_by} · {agent.owner}")
        st.write(agent.summary)
        for snippet in agent.code:
            with st.expander(snippet.title):
                found = code_snippets.source(snippet)
                if found is None:
                    st.caption(f"{snippet.path} isn't available on this server.")
                    continue
                code, line = found
                st.caption(f"`{snippet.path}:{line}` · {snippet.say}")
                st.code(code, language="python")
        for t in agent.tools:
            with st.expander(f"`{t.name}`"):
                st.markdown(
                    f"{t.does}\n\n"
                    f"- **Takes:** {t.takes}\n"
                    f"- **Returns:** {t.returns}"
                    + (f"\n- **Guardrail:** {t.guard}" if t.guard else "")
                )
                found = code_snippets.source(t.snippet)
                if found is None:
                    st.caption(f"{t.path} isn't available on this server.")
                    continue
                code, line = found
                st.caption(f"The code that runs it · `{t.path}:{line}`")
                st.code(code, language="python")

    st.subheader("How retrieval works")
    st.markdown(
        "| When | What happens |\n"
        "|---|---|\n"
        "| **Upload** (Course library) | Each file is split into passages: one per slide, PDF "
        "page or group of notebook cells. Plain text only, nothing is embedded yet. |\n"
        "| **New session** | Every library file (up to 100) is copied into the session, so its "
        "scores always refer to the exact notes it had. Later uploads don't change it. |\n"
        "| **First search** (③) | Passages are cut into 120-word chunks with 30-word overlap "
        "(Topic 8 lab), embedded with `text-embedding-3-small` and indexed for BM25. The index "
        "is cached by content, so sessions with the same library reuse it. |\n"
        "| **Every search** | The agent looks up the session's week in the course schedule, "
        "searches that week's files (plus undated ones), fuses BM25 and vector rankings with "
        "RRF and takes the top 5. Weak results: it rewrites the query or drops the week "
        "filter, at most twice. |"
    )
    st.markdown(
        "- **Which files count for a week?** Those whose name matches the schedule (e.g. "
        "`week08 Agentic RAG.pptx`). Unmatched files are searched every week, so keep the "
        "original IS469 file names.\n"
        "- **Does more files mean slower?** Barely. A search scores every chunk, but even "
        "~10,000 chunks take milliseconds; model calls dominate. The cost is one-time "
        "indexing (about 30–60 s for a full library), repeated when the library changes.\n"
        "- **The real trade-off is relevance:** more files, more near-misses competing for the "
        "top 5. The week filter keeps searches on topic."
    )

    st.subheader("How the Listener decides who spoke")
    st.markdown(
        "Two models listen separately, and the app combines them. Whisper hears *what* was "
        "said; pyannote hears *how many voices* there are and when each one talks, without "
        "knowing who they are. Names come only from comparing voices with the samples enrolled "
        "in Class & voices."
    )
    st.markdown(
        "| Stage | What happens | Can go wrong |\n"
        "|---|---|---|\n"
        "| 1 · Transcribe | Whisper writes the words, in pieces cut at pauses, with a time for "
        "every word | A piece can run across two speakers; names and terms get misspelt |\n"
        "| 2 · Split by voice | pyannote (diarisation) labels stretches of audio Speaker A, "
        "Speaker B… purely by how the voices sound | It can merge two similar voices into one "
        "speaker, or put part of a turn under the wrong speaker |\n"
        "| 3 · Name each speaker | All of a speaker's audio is turned into a voice embedding "
        "(SpeechBrain ECAPA) and compared with every enrolled sample by cosine similarity. "
        "The best match must score at least 0.35 and be 0.10 ahead of the next, else the "
        "speaker stays *unknown* or *ambiguous* | Not on its own: a merged speaker still gets "
        "one name for two people |\n"
        "| 4 · Words to speakers | Each word goes to the speaker talking at that moment, so a "
        "Whisper piece that runs across a turn change is split there | Word timings are off "
        "by a few hundredths of a second at the edges |\n"
        "| 5 · Check each line | Each line of 1 s or more is scored again on its own voice. If "
        "it clearly sounds like someone else, it becomes *ambiguous* | Lines under 1 s carry "
        "too little voice to check on their own |\n"
        "| 6 · Check each turn | Consecutive lines of one speaker are scored again as one turn, "
        "so a turn Whisper cut into short lines is still checked. A line is credited only if "
        "neither check names someone else | — |\n"
        "| 7 · A person confirms | ② Who spoke? shows every line with its speaker and a ▶ to "
        "hear it; the professor confirms before the session is created. Unknown and ambiguous "
        "lines are never scored | The professor can't reassign a line here yet, only confirm "
        "or discard |"
    )
    with st.expander("Worked example: why stage 6 exists (Demo 7)"):
        st.markdown(
            "The professor's last line in Demo 7 is *\"I don't think the evidence supports "
            "always. For facts that change, retrieval is usually the better tool. Let's stop "
            'there."*\n\n'
            '1. pyannote got the start right but put the last 2.5 s (*"retrieval is usually '
            "the better tool. Let's stop there\"*) under Tina's speaker.\n"
            "2. Whisper had cut that stretch into three pieces: 0.96 s, 0.70 s and 0.62 s.\n"
            "3. Stage 5 skips pieces under 1 s, so none was checked, and all three were "
            "credited to Tina: a student credited with words she never said.\n"
            "4. Stage 6 glues them back into one 2.5 s turn and scores it: prof 0.78, Tina "
            "0.07. The turn clearly isn't Tina, so it becomes *ambiguous*.\n\n"
            '**Why ambiguous and not "professor"?** The check only proves the voice doesn\'t '
            "match the label. Crediting the wrong student can change a grade; an ambiguous line "
            "is never scored, and the professor sees it in ② Who spoke?."
        )
    with st.expander("How well it works (measured on the 7 demo seminars)"):
        st.markdown(
            "Each demo's script says who really said every line, so each setting can be scored "
            "line by line (`eval/listener/`, results in `eval/results/listener-20261107.md`). "
            "8.3 minutes of audio, 64 lines, 26 of them students'.\n\n"
            "| Setting | Lines credited to the wrong student | Student lines right | "
            "Professor lines right |\n"
            "|---|---|---|---|\n"
            "| Before: Tina's rule (ambiguous whenever two voices pass 0.25) | 1 | 17/26 | "
            "34/36 |\n"
            "| Stages 3–5 | 1 | 24/26 | 35/36 |\n"
            "| **Stages 3–6 (the app now)** | **0** | **24/26** | **36/36** |\n"
            "| Perfect splitting (each line's true time span) | 0 | 26/26 | 36/36 |\n\n"
            "- The two student lines left are in Demo 6, where pyannote found 3 voices for 5 "
            "people. Both are marked ambiguous, not miscredited.\n"
            "- Changing the 0.35 / 0.10 thresholds made no difference: a person's own voice "
            "scores about 0.46–0.97 against their sample, anyone else's at most about 0.37.\n"
            "- The last row shows the voice model isn't the weak point: with perfect splitting "
            "every line is right. The errors come from stages 1 and 2.\n"
            "- Whisper's word error rate is 4.3% (mostly names and terms, e.g. *Laura* for "
            "LoRA). A full run takes about 1.7× the recording's length on the server's CPU, "
            "three quarters of it in pyannote.\n"
            "- Limits: cloned voices, no crosstalk or room noise, and only 26 student lines, "
            "so each difference is one line."
        )
    with st.expander("How the demo recordings were made (voice cloning)"):
        st.markdown(
            "- **Free and local.** F5-TTS, an open-source text-to-speech model, runs on our own "
            "server's CPU: no API, no per-use cost, about 2.5 minutes per 5-second line.\n"
            "- **How it clones.** It's given a few seconds of a person's enrolled sample plus "
            "the exact words said in it, and a new line to say. It generates the new line "
            "with the same pitch, tone and accent. Nothing is learnt permanently: it copies "
            "the voice from that one clip each time.\n"
            "- **Assembly.** Each line is generated on its own, then the lines are joined with "
            "short pauses, and every line's start and end time is saved. That timed script is "
            "what the ▶ buttons under each demo recording use.\n"
            "- **Checked before use.** Whisper must hear the scripted words, and the voice "
            "match must name the right person (all 64 lines passed). The guest is a built-in "
            "Mac voice that nobody enrolled, so the Listener must leave it *unknown*.\n"
            "- **Consent and privacy.** Everyone whose voice is cloned agreed to it. The audio "
            "stays on the server and is never committed to the public repository."
        )

    st.subheader("Guardrails")
    st.markdown(
        "- Transcript and slide text is treated as **data, never instructions** "
        "(prompt-injection defence).\n"
        "- **Unknown speakers are never scored**, and silent students get *No observed "
        "contribution* rather than a guess.\n"
        "- **No model can send email.** The professor approves the exact version (a SHA-256 "
        "fingerprint of the content and recipients); any edit cancels the approval.\n"
        "- **Test mode** redirects every email to one inbox, and an email whose outcome is "
        "unknown is never retried automatically, so no student gets it twice."
    )

    course_map.render()

    st.subheader("Under the hood: the code behind each topic")
    st.caption(
        "Read live from the source files, so this is exactly the code that runs. Open one to "
        "see the parameters."
    )
    for topic, snippets in code_snippets.TOPICS:
        st.markdown(f"**{topic}**")
        for snippet in snippets:
            found = code_snippets.source(snippet)
            with st.expander(snippet.title):
                if found is None:
                    st.caption(f"{snippet.path} isn't available on this server.")
                    continue
                code, line = found
                st.caption(f"`{snippet.path}:{line}` · {snippet.say}")
                st.code(code, language="python")

    st.button(
        "Start a class session", icon=":material/mic:", type="primary", on_click=go, args=("new",)
    )


# --- Session Summary ----------------------------------------------------------

elif view == "reflection":
    reflection_ui.render()

elif view == "monitoring":
    monitoring_view(records, go)

elif view == "downloads":
    st.title("Download data")
    st.markdown(
        '<p class="muted">The recordings, voice samples and database live only on this server. '
        "Choose what you need, prepare one zip and download it, for example to run the "
        "Listener or the evaluations on your own machine. Unpack it with "
        "<code>python tools/unpack_download.py classpartai-data.zip</code>: it puts every folder "
        "where the app and the evaluations look for it.</p>",
        unsafe_allow_html=True,
    )
    choices = exports.groups(DATA_DIR, ENROLLMENT_DIR, REPO_ROOT)
    sizes = {g.key: g.files() for g in choices if g.key != "database"}
    picked = []
    for group in choices:
        files = sizes.get(group.key)
        count = (
            f"{len(files)} files, {sum(f.stat().st_size for f, _ in files) / 1e6:.1f} MB"
            if files is not None
            else "one SQLite file"
        )
        tag = " · personal data" if group.personal else ""
        if st.checkbox(
            f"**{group.label}** ({count}{tag})",
            value=group.key in ("demo-seminars", "library", "results"),
            key=f"export-{group.key}",
            help=group.note,
        ):
            picked.append(group)
    if any(g.personal for g in picked):
        st.warning(
            "This includes voices or student records. Keep the zip off shared drives and "
            "delete it when you are done."
        )
    # Zips live in one folder; any older than an hour (another tab's, or a closed page's) and
    # this tab's previous zip are deleted, so copies of recordings don't pile up on the server.
    zips = Path(tempfile.gettempdir()) / "classpartai-exports"
    zips.mkdir(exist_ok=True)
    for old in zips.glob("*.zip"):
        if time.time() - old.stat().st_mtime > 3600:
            old.unlink(missing_ok=True)
    if picked and st.button("Prepare zip", type="primary"):
        if previous := st.session_state.pop("export", None):
            Path(previous["path"]).unlink(missing_ok=True)
        with st.spinner("Zipping…"):
            tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False, dir=zips)
            with tmp:
                rows = exports.build_archive(picked, DATA_DIR, tmp)
            st.session_state["export"] = {"path": tmp.name, "rows": rows}
    ready = st.session_state.get("export")
    if ready and Path(ready["path"]).is_file():
        st.dataframe(ready["rows"], hide_index=True, width="stretch")
        with open(ready["path"], "rb") as zipped:
            st.download_button(
                "Download classpartai-data.zip",
                zipped,
                file_name="classpartai-data.zip",
                mime="application/zip",
            )

elif view == "evaluation":
    evaluation_view(records)

elif view == "summary":
    inputs = records.inputs(session_id)
    meta = by_id[session_id]

    st.title(f"Session Summary · {inputs.sessionTitle}")

    st.caption(f"{when(meta['created_at'])} · {inputs.courseTitle} · {len(inputs.roster)} students")

    st.button(
        "← Back to Assessment workflow",
        on_click=go,
        args=("session", session_id),
    )

    st.divider()

    st.subheader("Seminar discussion overview")

    st.write(
        "Generate an AI briefing covering the main discussion topics, "
        "agreements, disagreements, unresolved questions, "
        "participation and suggested follow-ups."
    )

    # Keep each session's summary separate
    summary_key = f"session_summary_{session_id}"

    if not (os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")):
        st.error("Set OPENAI_API_KEY (or GROQ_API_KEY) in your .env file.")

    else:
        if st.button(
            "Generate summary",
            type="primary",
            key=f"generate_summary_{session_id}",
        ):
            with st.spinner("Analysing the seminar discussion..."):
                try:
                    result = analyse_session(
                        transcript=inputs.transcript,
                        generate_json=generate_summary_json,
                    )

                    st.session_state[summary_key] = result

                except Exception as exc:
                    st.error(f"Summary generation failed: {exc}")

        # Display the generated summary
        if summary_key in st.session_state:
            st.divider()
            render_session_summary(st.session_state[summary_key])
    # --- Assessment Workflow ------------------------------------------------------

elif view == "session":
    inputs = records.inputs(session_id)
    meta = by_id[session_id]
    latest = records.latest_draft(session_id)
    approval = records.active_approval(session_id) if latest else None
    deliveries = records.deliveries(session_id)
    sent = bool(deliveries) and all(d["state"] == "accepted" for d in deliveries)
    done = (
        {1, 2}
        | ({3} if latest else set())
        | ({4} if approval else set())
        | ({5} if sent else set())
    )
    step = requested_step or default_step(session_id)
    step_bar("session", step, done, {1, 2, 3, 4, 5})
    title_col, delete_col = st.columns([6, 1], vertical_alignment="bottom")
    title_col.title(inputs.sessionTitle)
    if delete_col.button(
        "Delete", icon=":material/delete:", key=f"delete-{session_id}", width="stretch"
    ):
        confirm_delete(session_id, inputs.sessionTitle)
    st.markdown(
        f'<p class="muted">{escape(when(meta["created_at"]))} · {escape(inputs.courseTitle)} · '
        f"{len(inputs.roster)} students · {escape(inputs.rubric.title)}</p>",
        unsafe_allow_html=True,
    )

    if step == 1:
        with st.container(border=True):
            st.markdown("**① Record** · the class recording this session was made from")
            audio = recording_of(session_id)
            if audio:
                recording_player(audio, f"seek-{session_id}")
            else:
                st.caption(
                    "No recording: this session started from a ready-made transcript or an "
                    "imported file."
                )
            script = (records.listener_run(session_id) or {}).get("script")
            if script:
                show_script(script, f"seek-{session_id}" if audio else None)
        st.button(
            "Next: ② Who spoke? →", on_click=go, args=("session", session_id, 2), key="next-2"
        )

    elif step == 2:
        with st.container(border=True):
            st.markdown(
                "**② Who spoke?** · the Listener's attribution, as reviewed when the session "
                "was created. Voice-match scores are in ③ AI assessment → Listener."
            )
            who_spoke(
                inputs.transcript.turns,
                {s.id: s.displayName for s in inputs.roster},
                recording_of(session_id),
                f"who-{session_id}",
            )
        st.button(
            "Next: ③ AI assessment →", on_click=go, args=("session", session_id, 3), key="next-3"
        )

    elif step == 3:
        live = live_runs().get(session_id)
        running = bool(live and live["thread"].is_alive())
        tabs = st.tabs(TABS, key="agent", on_change="rerun", bind="query-params")
        for name, tab in zip(TABS, tabs, strict=True):
            if not tab.open:
                continue
            with tab:
                if name != "Overview":

                    def agent_panel(name=name):
                        render_agent(name, records, session_id, inputs, live_runs().get(session_id))
                        entry = live_runs().get(session_id)
                        if entry and entry["ended"] and not entry.get("reported"):
                            entry["reported"] = True
                            st.rerun()

                    st.fragment(run_every=2 if running else None)(agent_panel)()
                    recording = recording_of(session_id)
                    if name == "Listener" and recording:
                        with st.expander("Play any line of the recording"):
                            recording_player(recording, f"seek-{session_id}")
                            show_transcript(
                                inputs.transcript.turns,
                                {s.id: s.displayName for s in inputs.roster},
                                f"seek-{session_id}",
                            )
                    if name == "Evidence / Research":
                        with st.expander("Ask the course notes", icon=":material/search:"):
                            st.write(
                                "Ask the evidence agent to check something said in class "
                                "against the course documents. It chooses its own searches "
                                "and must cite exact excerpts; it never "
                                "scores."
                            )
                            question = st.text_input(
                                "Question",
                                placeholder="Is Alex's latency point supported by the notes?",
                            )
                            turn_labels = {
                                t.id: f"{t.id} · {speaker_name(inputs, t)}: {t.text[:60]}"
                                for t in inputs.transcript.turns
                            }
                            turn_ids = st.multiselect(
                                "Turns (1–8)",
                                list(turn_labels),
                                format_func=turn_labels.__getitem__,
                                max_selections=8,
                            )
                            crit = {c.id: c.title for c in inputs.rubric.criteria}
                            criterion_ids = st.multiselect(
                                "Rubric criteria",
                                list(crit),
                                format_func=crit.__getitem__,
                                default=list(crit)[:1],
                            )
                            ready = bool(len(question.strip()) >= 5 and turn_ids and criterion_ids)
                            if st.button("Investigate", type="primary", disabled=not ready):
                                use_research = config.EVIDENCE_AGENT == "research"
                                driver = (
                                    None
                                    if use_research
                                    else configured_driver(EVIDENCE_INSTRUCTIONS, EVIDENCE_TOOLS)
                                )
                                if driver is None and not use_research:
                                    st.error("No model configured (set OPENAI_API_KEY).")
                                else:
                                    log = st.status(
                                        "The evidence agent is investigating…", expanded=True
                                    )
                                    shown = [0]

                                    def checkpoint(progress, shown=shown, log=log):
                                        for a in progress.actions[shown[0] :]:
                                            if a["outcome"] == "started":
                                                break
                                            icon = (
                                                ":green[:material/check:]"
                                                if a["outcome"] == "ok"
                                                else ":red[:material/block:]"
                                            )
                                            log.write(f"{icon} `{a['tool']}`: {a['summary']}")
                                            shown[0] += 1

                                    request = Investigation(
                                        sessionId=session_id,
                                        question=question,
                                        turnIds=turn_ids,
                                        criterionIds=criterion_ids,
                                    )
                                    if (
                                        use_research
                                    ):  # ② Research (research/bridge.py), same contract
                                        from classpartai.research import bridge

                                        with usage.tracking(session_id=session_id):
                                            outcome = bridge.investigate(
                                                request, inputs, None, checkpoint
                                            )
                                    else:
                                        if driver is None:
                                            raise RuntimeError("Model configuration blocked")
                                        with usage.tracking(session_id=session_id):
                                            outcome = investigate(
                                                request,
                                                inputs,
                                                driver,
                                                CourseIndex(inputs),
                                                checkpoint,
                                            )
                                    records.save_evidence_run(session_id, question, outcome)
                                    log.update(
                                        label=f"Evidence agent: {outcome.status} "
                                        f"({outcome.stopReason})",
                                        state="complete",
                                    )
                                    # Redraw so the Evidence tab lists this new check.
                                    st.toast("Evidence check saved: replay it above in this tab")
                                    st.rerun()
                            for ev in records.evidence_runs(session_id):
                                bundle = ev["progress"]["bundle"]
                                with st.expander(f"{ev['status']} · {ev['question']}"):
                                    calls = ev["progress"]["modelCalls"]
                                    st.caption(
                                        f"Stop reason: {ev['stop_reason']} · model calls {calls}"
                                    )
                                    if bundle:
                                        st.write(bundle["explanation"])
                                        for c in bundle["citations"]:
                                            st.markdown(
                                                f"> {c['excerpt']}\n\n— {c['title']}, "
                                                f"p. {c['page']} · "
                                                f"*{c['relationship']}*"
                                            )
                                        for g in bundle["gaps"]:
                                            st.warning(f"Gap: {g}")
                                        for c in bundle["conflicts"]:
                                            st.error(f"Conflict: {c}")
                                    for a in ev["progress"]["actions"]:
                                        st.caption(f"{a['tool']} ({a['outcome']}): {a['summary']}")

                    continue
                overview(records, session_id, inputs, live)
                col_run, col_blank, _ = st.columns([1, 1, 2])
                if col_run.button(
                    "Working…"
                    if running
                    else "Generate assessment"
                    if latest is None
                    else "Regenerate assessment",
                    type="primary",
                    width="stretch",
                    disabled=running,
                ):
                    st.session_state.pop(replay_key(session_id), None)
                    start_run(session_id)
                    st.rerun()
                if (
                    latest is None
                    and not running
                    and col_blank.button("Write it myself", width="stretch")
                ):
                    records.create_professor_draft(session_id)
                    st.rerun()
                if running:  # a run started elsewhere (another tab) ends any replay
                    st.session_state.pop(replay_key(session_id), None)
                replaying, replayed = (
                    (False, None) if running else replay_section(session_id, inputs)
                )
                if live and replay_key(session_id) not in st.session_state:
                    run_panel(session_id, inputs)
                # A finished replay shows the draft its run left, not a later version.
                shown = replayed or latest
                if replaying:
                    st.caption("The stored draft is shown here when the replay finishes.")
                elif shown:
                    origin = "AI proposal" if shown.origin == "model" else "professor edit"
                    st.markdown(f"#### Version {shown.version} · {origin}")
                    if latest is not None and shown.id != latest.id:
                        st.caption(
                            f"From the replayed run. The current version is {latest.version}: "
                            "close the replay to see it. ④ Approve always uses the current one."
                        )
                    if running:
                        st.caption("A new run is working; this is the previous version.")
                    st.caption(shown.content.revisionNote)
                    bundles = dict(records.evidence_for(session_id))
                    criteria = {c.id: c.title for c in inputs.rubric.criteria}
                    turns = {t.id: t for t in inputs.transcript.turns}
                    for s in inputs.roster:
                        total = totals(shown.content, inputs, s.id)
                        headline = (
                            f"{total['total']:g}/{total['maximum']}"
                            if total["total"] is not None
                            else f"{total['assessedCriteria']}/{total['totalCriteria']} assessed"
                        )
                        with st.expander(f"**{s.displayName}** · {headline}"):
                            fb = next(
                                (x for x in shown.content.feedback if x.studentId == s.id), None
                            )
                            if fb:
                                said = own_turns(inputs, s.id)  # as the email shows it
                                st.markdown(
                                    quote_html(fb.strengths, said)
                                    + "<br><br><b>Next step:</b> "
                                    + quote_html(fb.nextStep, said),
                                    unsafe_allow_html=True,
                                )
                                if fb.limitations:
                                    st.caption("Limitations: " + "; ".join(fb.limitations))
                            else:
                                st.warning("No feedback draft yet; every roster student needs one.")
                            st.caption(
                                "Observed attributed contributions: "
                                f"{observed_count(inputs, s.id)} "
                                f"(counts are separate from judgement). {total['limitation']}."
                            )
                            for f in [x for x in shown.content.findings if x.studentId == s.id]:
                                verdict = (
                                    f"proposed {f.score:g}"
                                    if f.status == "scored"
                                    else "insufficient evidence, no score"
                                )
                                st.markdown(f"**{criteria[f.criterionId]}: {verdict}**")
                                st.markdown(
                                    quote_html(f.justification, {t: turns[t].text for t in turns}),
                                    unsafe_allow_html=True,
                                )
                                if f.limitations:
                                    st.caption("Limitations: " + "; ".join(f.limitations))
                                for tid in f.turnIds:
                                    st.caption(f"{tid}: {turns[tid].text}")
                                for c in f.citations:
                                    st.markdown(citation_text(bundles, c))
                    st.button(
                        "Next: ④ Approve →",
                        on_click=go,
                        args=("session", session_id, 4),
                    )

    elif step == 4:
        if latest is None:
            st.info("Run the agents in ③ AI assessment first (or write the draft yourself).")
        else:
            # The saved audit already repeats the deterministic checks: one entry per issue ID.
            open_issues = list(
                {
                    i.id: i
                    for i in [*audit_draft(latest.content, inputs), *latest.content.audit.issues]
                    if i.disposition == "open"
                }.values()
            )
            blocking = [i for i in open_issues if i.severity == "blocking"]
            with st.container(border=True):
                st.markdown(
                    f"**Version {latest.version}** · "
                    + (
                        "the auditor has reviewed it"
                        if latest.content.audit.modelReviewed
                        else "not audited by the AI auditor"
                    )
                    + f" · {len(open_issues)} open issue(s)"
                )

                def issue_text(i) -> str:
                    resolution = f": {i.resolution}" if i.resolution else ""
                    who = next((s.displayName for s in inputs.roster if s.id == i.studentId), "")
                    return (f"**{who}** · " if who else "") + f"{i.detail}{resolution}"

                for i in blocking:
                    st.error(issue_text(i))
                review = [i for i in open_issues if i.severity != "blocking"]
                if review:
                    with st.expander(f"{len(review)} issue(s) to review", expanded=not blocking):
                        for i in review:
                            st.markdown(f":orange[:material/warning:] {issue_text(i)}")
                if not open_issues:
                    st.success("No open issues.")
            briefing_now = records.summary_for(session_id)
            if briefing_now:
                with st.expander("Seminar briefing (from the Summary pipeline)"):
                    render_session_summary(briefing_now)
            with st.expander("Edit the draft (saves a new version)"):
                st.caption(
                    "Saving findings or feedback invalidates prior approvals. Invalid scores, "
                    "attribution and citations are refused."
                )
                as_json = st.toggle("Edit as JSON instead", key=f"json-{latest.id}")
                if as_json:
                    proposal_json = json.dumps(
                        {
                            "findings": [f.model_dump() for f in latest.content.findings],
                            "feedback": [f.model_dump() for f in latest.content.feedback],
                        },
                        indent=2,
                    )
                    editor = st.text_area(
                        "Findings and feedback JSON",
                        proposal_json,
                        height=300,
                        key=f"ed-{latest.id}",
                    )
                else:
                    edited = draft_form(latest, inputs)
                note = st.text_input("Reason for this edit", key=f"note-{latest.id}")
                if st.button("Save new professor version", disabled=len(note.strip()) < 3):
                    try:
                        proposal = (
                            Proposal.model_validate_json(editor)
                            if as_json
                            else Proposal.model_validate(edited)
                        )
                        records.append_draft(
                            session_id, proposal, "professor", note, latest.version
                        )
                        st.rerun()
                    except (Unprocessable, ValueError) as exc:
                        st.error(str(exc))

            if approval:
                note = approval["acknowledgement"] or "no issues"
                st.success(f"Version {latest.version} approved by {approval['approver']}: {note}")
                st.button(
                    "Next: ⑤ Send →",
                    type="primary",
                    on_click=go,
                    args=("session", session_id, 5),
                )
            else:
                if blocking:
                    st.error(
                        f"Version {latest.version} can't be approved yet: fix the blocking "
                        "issues above (run the agents again, or edit the draft)."
                    )
                ack = st.checkbox(
                    f"I reviewed version {latest.version}, its evidence, gaps and open issues.",
                    key=f"ack-{latest.id}",
                )
                col_why, col_who = st.columns([3, 1])
                reason = col_why.text_input(
                    "Why you're approving with open issues (at least 10 characters)"
                    if open_issues
                    else "Note (optional)",
                    key=f"why-{latest.id}",
                    placeholder="e.g. Checked the flags; scores are fair for this seminar",
                )
                approver = col_who.text_input("Approving as", "Prof (demo)")
                short = bool(open_issues) and len(reason.strip()) < 10
                if st.button(
                    f"Approve version {latest.version}",
                    type="primary",
                    disabled=bool(blocking) or not ack or short,
                ):
                    try:
                        records.approve_draft(session_id, latest.id, ack, reason, approver)
                        st.rerun()
                    except Unprocessable as exc:
                        st.error(str(exc))
                if not blocking and (not ack or short):
                    missing = []
                    if not ack:
                        missing.append("tick the review box")
                    if short:
                        missing.append(
                            f"write a reason of 10+ characters (now {len(reason.strip())})"
                        )
                    st.caption("To approve: " + " and ".join(missing) + ".")
                st.caption("Approval is separate from sending. An auditor pass is not approval.")

    else:
        current = {r["student_id"]: r["email"] for r in records.recipients(session_id)}
        test_mode = DeliverySettings.from_env()
        with st.expander(f"Recipients · {len(current)}/{len(inputs.roster)} set"):
            st.caption(
                "Recipients are separate roster records, never chosen by a model. Any change "
                "invalidates approvals."
            )
            if st.button("Fill from class list"):
                st.toast(f"{set_recipients_from_classlist(session_id, inputs)} recipient(s) set.")
                st.rerun()
            for s in inputs.roster:
                col_name, col_mail, col_save = st.columns([2, 4, 1])
                col_name.write(s.displayName)
                email = col_mail.text_input(
                    "Email",
                    current.get(s.id, ""),
                    key=f"rcpt-{session_id}-{s.id}",
                    label_visibility="collapsed",
                )
                if col_save.button("Save", key=f"save-{s.id}"):
                    try:
                        records.set_recipient(session_id, s.id, email or "")
                        st.rerun()
                    except Unprocessable as exc:
                        st.error(str(exc))
        if latest is None or approval is None:
            st.info("Approve a version in ④ Approve first; only the approved version is sent.")
        else:
            st.markdown(f"#### Emails for version {latest.version}")
            if test_mode.test_mode:
                st.caption(f"Test mode: all of them go to {test_mode.test_recipient}.")
            for s in inputs.roster:
                with st.expander(
                    f"{s.displayName} → {current.get(s.id, '(no recipient)')}",
                    icon=":material/mail:",
                ):
                    try:
                        st.text(feedback_email(records, session_id, s.id, latest))
                    except StopIteration:
                        st.warning("No feedback for this student in the approved version.")
            if st.button(
                f"Send {len(inputs.roster)} emails via AgentMail",
                type="primary",
            ):
                transport = AgentMailTransport(
                    os.getenv("AGENTMAIL_API_KEY", ""), os.getenv("AGENTMAIL_INBOX", "")
                )
                try:
                    results = deliver_approved(
                        records, session_id, approval["id"], transport, DeliverySettings.from_env()
                    )
                    st.toast(", ".join(f"{r['studentId']}: {r['state']}" for r in results))
                    st.rerun()
                except Unprocessable as exc:
                    st.error(str(exc))
            st.caption(
                "Accepted means AgentMail accepted it, not confirmed inbox delivery. Accepted "
                "messages are never resent; ambiguous outcomes are never retried automatically."
            )
        if deliveries:
            names = {s.id: s.displayName for s in inputs.roster}
            st.dataframe(
                [
                    {
                        "Student": names.get(d["student_id"], d["student_id"]),
                        "Recipient": d["recipient"],
                        "State": d["state"],
                        "Attempts": d["attempts"],
                        "Updated": d["updated_at"],
                    }
                    for d in deliveries
                ],
                hide_index=True,
                width="stretch",
            )
