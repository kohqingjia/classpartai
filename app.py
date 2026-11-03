"""Streamlit app for ClassPart AI. Run with `uv run streamlit run app.py`.

The workflow follows Le Yong's design (feat/assessment-foundation), ported to Python:
Session (reviewed transcript + roster + rubric + course documents) -> Evidence -> Assessment
(the coordinator agent drafts findings and feedback) -> professor approval of the exact version
-> delivery through AgentMail. Recordings come in through Tina's Listener pipeline.

Each session follows five steps, with read-only agent inspectors inside AI assessment.
"""

import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

from classpartai import config
from classpartai.agent_ui import TABS, delivery_view, listener_view, overview, render_agent
from classpartai.agents import listener
from classpartai.assessment import AssessmentInputs, parse_inputs
from classpartai.classlist import ClassList
from classpartai.config import DATA_DIR, ENROLLMENT_DIR, REPO_ROOT
from classpartai.evidence import INSTRUCTIONS as EVIDENCE_INSTRUCTIONS
from classpartai.evidence import TOOL_DEFINITIONS as EVIDENCE_TOOLS
from classpartai.evidence import CourseIndex, Investigation, investigate
from classpartai.library import SUPPORTED as LIBRARY_TYPES
from classpartai.library import Library
from classpartai.models import configured_driver
from classpartai.participation.coordinator import coordinate
from classpartai.participation.delivery import (
    AgentMailTransport,
    DeliverySettings,
    deliver_approved,
)
from classpartai.participation.records import Records
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import Unprocessable
from classpartai.retrieval import examined_of, searches_of
from classpartai.ui import vault_html

DATA = REPO_ROOT / "data"
REGISTRY_PATH = ENROLLMENT_DIR / "registry.json"
AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
SGT = timezone(timedelta(hours=8))

# Notion-style touches Streamlit's theme can't express: left-aligned sidebar rows, a big title.
PAGE_CSS = """<style>
[data-testid="stAppViewContainer"] { background:#0d1119; }
[data-testid="stSidebar"] { background:#10151e; }
[data-testid="stSidebar"] button[data-testid^="stBaseButton"] > div { justify-content:flex-start; }
[data-testid="stMainBlockContainer"] { max-width:1400px; padding:2.5rem 3rem 5rem; }
h1 { font-size:2.35rem !important; font-weight:650 !important; letter-spacing:-.04em; }
h2,h3 { letter-spacing:-.025em; }
h4 { font-size:1rem !important; padding-top:1rem !important; }
[data-testid="stCaptionContainer"] { color:#9ba6b8; font-variant-numeric:tabular-nums; }
[data-testid="stMetricValue"] { font-size:1.7rem; letter-spacing:-.03em; }
[data-testid="stVerticalBlockBorderWrapper"] > div { border-color:#273142; border-radius:12px; }
[data-baseweb="tab-list"] { gap:1.2rem; overflow-x:auto; }
[data-baseweb="tab"] { font-size:.86rem; white-space:nowrap; }
[data-testid="stSidebar"] [data-testid="stAlert"] { font-size:.8rem; }
button { transition:none; }
.muted { color:#9ba6b8; }
@media(max-width:700px) {
 [data-testid="stMainBlockContainer"] { padding:1.5rem 1rem 3rem; }
 h1 { font-size:1.8rem !important; }
 [data-testid="stSegmentedControl"] { overflow-x:auto; }
}
@media(prefers-reduced-motion:reduce) { *,*::before,*::after {
 animation:none !important; transition:none !important; } }
</style>"""


# --- Shared state -----------------------------------------------------------------------------


@st.cache_resource
def services() -> tuple[Records, ClassList]:
    # A new file: the earlier Action-harness build left a classpartai.db with an incompatible
    # `sessions` table.
    return Records(DATA_DIR / "assessments.db"), ClassList(DATA_DIR / "classlist.json")


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


def load_registry() -> dict:
    return json.loads(REGISTRY_PATH.read_text()) if REGISTRY_PATH.exists() else {}


def save_registry(registry: dict) -> None:
    ENROLLMENT_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(registry, indent=2))


def to_wav(upload, dest: Path) -> Path:
    """Convert any uploaded audio to 16 kHz mono WAV, the format the speech models expect."""
    with tempfile.NamedTemporaryFile(suffix=Path(upload.name).suffix) as src:
        src.write(upload.getbuffer())
        src.flush()
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", src.name]
        subprocess.run([*cmd, "-ac", "1", "-ar", "16000", dest], check=True)
    return dest


def when(iso: str) -> str:
    """'Wed 29 Oct, 3:50 PM' in Singapore time."""
    stamp = datetime.fromisoformat(iso).astimezone(SGT)
    return stamp.strftime("%a %-d %b, %-I:%M %p")


def default_title() -> str:
    return datetime.now(SGT).strftime("Seminar @%A %-I:%M %p")


def go(view: str, session: str | None = None) -> None:
    if "session" in st.query_params:
        del st.query_params["session"]
    st.session_state.view = view
    if session:
        st.session_state.session_id = session
        st.query_params["session"] = session


def speaker_name(inputs: AssessmentInputs, turn) -> str:
    sp = turn.speaker
    if sp.kind == "student":
        return next(s.displayName for s in inputs.roster if s.id == sp.studentId)
    return f"{sp.label} ({sp.kind})"


def show_transcript(turns, names: dict[str, str]) -> None:
    """The transcript as a conversation. Uncertain turns are greyed out: they are never scored."""
    for t in turns:
        sp = t.speaker
        stamp = f"{t.startMs // 60000}:{t.startMs // 1000 % 60:02d}"
        if sp.kind == "student":
            who, avatar = names.get(sp.studentId, sp.studentId), "🧑‍🎓"
        elif sp.kind == "professor":
            who, avatar = sp.label, "🎓"
        else:
            who, avatar = f"{sp.label} · speaker uncertain", "❔"
        with st.chat_message(who, avatar=avatar):
            st.caption(f"**{who}** · {stamp} · {t.id}")
            st.markdown(f":gray[{t.text}]" if sp.kind == "uncertain" else t.text)


def set_recipients_from_classlist(session_id: str, inputs: AssessmentInputs) -> int:
    count = 0
    for s in inputs.roster:
        student = classlist.get(s.id)
        if student:
            records.set_recipient(session_id, s.id, student.email)
            count += 1
    return count


records, classlist = services()

st.set_page_config(page_title="ClassPart AI", page_icon="🎓", layout="wide")
st.html(PAGE_CSS)

# --- Sidebar: like Notion's meeting list ------------------------------------------------------

sessions = records.sessions()
by_id = {s["id"]: s for s in sessions}
if "view" not in st.session_state:
    st.session_state.view = "home"
if st.session_state.get("session_id") not in by_id:
    st.session_state.session_id = next(iter(by_id), None)
if st.session_state.view == "session" and not sessions:
    st.session_state.view = "new"

with st.sidebar:
    st.markdown("### ◈ ClassPart AI")
    st.caption("IS469 · PARTICIPATION STUDIO")
    st.button(
        "Home",
        width="stretch",
        on_click=go,
        args=("home",),
        type="secondary" if st.session_state.view == "home" else "tertiary",
    )
    st.button(
        "🎙️ New class session",
        width="stretch",
        type="secondary" if st.session_state.view == "new" else "tertiary",
        on_click=go,
        args=("new",),
    )
    st.caption("Class sessions")
    for s in sessions:
        selected = st.session_state.view == "session" and s["id"] == st.session_state.session_id
        title = s["title"] if len(s["title"]) <= 30 else s["title"][:29] + "…"
        st.button(
            f"📝 {title}",
            key=f"open-{s['id']}",
            help=f"{s['course_title']} · {when(s['created_at'])}",
            width="stretch",
            type="secondary" if selected else "tertiary",
            on_click=go,
            args=("session", s["id"]),
        )
    if not sessions:
        st.caption("No sessions yet.")
    st.divider()
    st.button(
        "📚 Course library",
        width="stretch",
        type="secondary" if st.session_state.view == "library" else "tertiary",
        on_click=go,
        args=("library",),
    )
    st.button(
        "👥 Class & voices",
        width="stretch",
        type="secondary" if st.session_state.view == "classlist" else "tertiary",
        on_click=go,
        args=("classlist",),
    )
    if os.getenv("EMAIL_TEST_MODE", "true").lower() != "false":
        recipient = os.getenv("EMAIL_TEST_RECIPIENT", "(not set)")
        st.caption(f"✉️ Test mode: every email goes to {recipient}")
    if not os.getenv("OPENAI_API_KEY"):
        st.warning("No OPENAI_API_KEY: agent runs will be blocked.")

linked_session = st.query_params.get("session")
if linked_session in by_id:
    st.session_state.view = "session"
    st.session_state.session_id = linked_session
view = st.session_state.view
session_id = st.session_state.session_id


def open_session(new_inputs: AssessmentInputs, *, from_listener=False) -> None:
    new_id = records.create_session(new_inputs)
    if from_listener:
        records.save_listener_run(new_id, st.session_state.pop("pending_listener"))
        recording = DATA_DIR / "recordings" / f"{new_id}.wav"
        recording.parent.mkdir(parents=True, exist_ok=True)
        recording.write_bytes(st.session_state.pop("pending_audio"))
    st.session_state.step = "Who spoke?"
    n = set_recipients_from_classlist(new_id, new_inputs)
    go("session", new_id)
    st.toast(f"Session created; {n} recipient(s) filled from the class list.")
    st.rerun()


# --- New class session ------------------------------------------------------------------------

if view == "home":
    st.caption("CLASS PARTICIPATION / HUMAN REVIEWED")
    st.title("A clearer view of every contribution.")
    st.write(
        "Turn class conversations into evidence-backed feedback, with every agent's work in view."
    )
    st.divider()
    st.subheader("Prepare your next class")
    checks = [
        (
            "01",
            "Build your course library",
            "Slides, readings and labs become traceable evidence.",
            "library",
            bool(course_library().entries()),
        ),
        (
            "02",
            "Set up class & voices",
            "Add the roster and consented voice samples.",
            "classlist",
            bool(classlist.all()),
        ),
        (
            "03",
            "Start a class session",
            "Record, review speakers and open the agent workspace.",
            "new",
            bool(sessions),
        ),
    ]
    for col, (num, title, text, destination, ready) in zip(st.columns(3), checks, strict=True):
        with col.container(border=True):
            st.caption(num + " / " + ("READY" if ready else "TO DO"))
            st.subheader(title)
            st.write(text)
            st.button(
                "Open " + title.lower(),
                key="home-" + destination,
                on_click=go,
                args=(destination,),
                width="stretch",
            )
    st.caption("Record → Who spoke? → AI assessment → Approve → Send")
    st.subheader("Recent sessions")
    if not sessions:
        st.info("Your first session starts with a recording or the included demo transcript.")
    for item in sessions[:6]:
        with st.container(border=True):
            a, b = st.columns([4, 1])
            a.write(item["title"])
            a.caption(item["course_title"] + " · " + when(item["created_at"]))
            b.button(
                "Open session",
                key="home-session-" + item["id"],
                on_click=go,
                args=("session", item["id"]),
            )

elif view == "new":
    roster = list(classlist.all().values())
    st.session_state.setdefault("new-title", default_title())
    st.title(st.session_state["new-title"] or "Untitled session")
    col_title, col_course = st.columns(2)
    title = col_title.text_input("Title", key="new-title")
    course = col_course.text_input("Course", "IS469 Gen AI with LLMs")

    with st.container(border=True):
        st.markdown("**🎙️ Class recording**")
        if not roster:
            st.warning("Add students on the Class & voices first, so the recording has a roster.")
        col_rec, col_up = st.columns(2)
        recorded = col_rec.audio_input("Start transcribing", key="mic")
        uploaded = col_up.file_uploader("…or upload a recording", type=AUDIO_TYPES)
        audio = recorded or uploaded
        st.caption(
            "ClassPart AI transcribes the recording, works out who spoke, then checks, scores and "
            "drafts feedback once you've reviewed the transcript. By recording, you confirm "
            "everyone being recorded has agreed to it."
        )
        if st.button("Transcribe", type="primary", disabled=not (audio and roster)):
            if not REGISTRY_PATH.exists():
                save_registry({})
            try:
                process_audio, note, lock = load_listener()
                with tempfile.TemporaryDirectory() as tmp, lock:
                    with st.spinner("Transcribing and identifying speakers…"):
                        wav = to_wav(audio, Path(tmp) / "rec.wav")
                        result = process_audio(str(wav))
                        st.session_state.pending_audio = wav.read_bytes()
            except Exception as exc:
                st.error(
                    f"Couldn't process the recording ({str(exc).splitlines()[0][:300]}). "
                    "You can still use the demo seminar below."
                )
            else:
                ids = {p["name"]: pid for pid, p in load_registry().items()}
                st.session_state.pending_transcript = listener.to_transcript(
                    result, ids, "review-1"
                )
                st.session_state.pending_meta = (title, course)
                st.session_state.listener_note = note
                st.session_state.pending_listener = {**result, "note": note}

        pending = st.session_state.get("pending_transcript")
        if pending:
            st.divider()
            st.markdown("**Transcript: check who said what before it's used**")
            if st.session_state.get("listener_note"):
                st.info(st.session_state.listener_note)
            names = {s.person_id: s.name for s in roster}
            show_transcript(pending.turns, names)
            reviewed = st.checkbox("I have reviewed this transcript's attribution")
            if reviewed and st.button("Create session from transcript", type="primary"):
                title, course = st.session_state.pop("pending_meta")
                open_session(
                    AssessmentInputs(
                        formatVersion=1,
                        provenance="reviewed",
                        courseTitle=course,
                        sessionTitle=title,
                        roster=[{"id": s.person_id, "displayName": s.name} for s in roster],
                        transcript=st.session_state.pop("pending_transcript"),
                        rubric=json.loads((DATA / "default_rubric.json").read_text()),
                        documents=course_library().documents()
                        or json.loads(config.COURSE_DOCUMENTS.read_text()),
                    ),
                    from_listener=True,
                )

    st.markdown('<p class="muted">No recording to hand?</p>', unsafe_allow_html=True)
    col_demo, col_fixture, _ = st.columns([1, 1, 2])
    if col_demo.button("Skip to the demo transcript", width="stretch"):
        for pid, entry in json.loads((DATA / "sample_classlist.json").read_text()).items():
            if classlist.get(pid) is None:
                classlist.upsert(entry["name"], entry["email"])
        demo = parse_inputs((DATA / "sample_assessment.json").read_text())
        open_session(
            AssessmentInputs.model_validate(
                {**demo.model_dump(), "documents": with_library(demo.documents)}
            )
        )
    if col_fixture.button("Use Le Yong's fixture", width="stretch"):
        open_session(parse_inputs((DATA / "fixture-fictional.json").read_text()))
    files = len(course_library().entries())
    st.caption(
        f"New sessions search the {files} file(s) in the 📚 Course library"
        if files
        else "📚 The Course library is empty: sessions from recordings use the demo course notes."
    )
    with st.expander("Import a session file (JSON)"):
        st.caption("A reviewed session file: roster, transcript, rubric and course documents.")
        upload = st.file_uploader("Session JSON", type=["json"])
        if upload and st.button("Import", type="primary"):
            try:
                open_session(parse_inputs(upload.getvalue().decode()))
            except ValueError as exc:
                st.error(str(exc))

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
        documents = [e["document"] for e in entries]
        show_vault(documents, agent="Course library", height=460)
        for entry in entries:
            doc = entry["document"]
            col_name, col_count, col_when, col_remove = st.columns([4, 2, 2, 1])
            col_name.markdown(f"📄 **{doc['title']}**  \n:gray[{entry['file']}]")
            col_count.write(f"{len(doc['passages'])} passages")
            col_when.caption(when(entry["uploadedAt"]))
            if col_remove.button("Remove", key=f"lib-rm-{entry['file']}"):
                library.remove(entry["file"])
                st.rerun()
        st.caption(
            "Sessions keep the documents they were created with, so removing a file here "
            "doesn't change past evidence or scores."
        )
    else:
        st.info("No files yet. Upload the slides for the topics your seminars cover.")

# --- Class list -------------------------------------------------------------------------------

elif view == "classlist":
    st.title("Class & voices")
    st.write(
        "Add each student with their email. A 20–30 second clip of them speaking alone lets the "
        "Listener recognise them; only add a voice sample for people who have agreed to it."
    )
    with st.form("add-student", clear_on_submit=True):
        name = st.text_input("Name")
        email_address = st.text_input("Email")
        sample = st.file_uploader("Voice sample (optional)", type=AUDIO_TYPES)
        if st.form_submit_button("Add student"):
            if not name.strip() or "@" not in email_address:
                st.error("Enter a name and a valid email.")
            else:
                student = classlist.upsert(name, email_address)
                if sample:
                    ENROLLMENT_DIR.mkdir(parents=True, exist_ok=True)
                    to_wav(sample, ENROLLMENT_DIR / f"{student.person_id}.wav")
                    registry = load_registry()
                    registry[student.person_id] = {
                        "name": student.name,
                        "audio_file": f"{student.person_id}.wav",
                    }
                    save_registry(registry)
                st.success(f"Added {student.name}.")

    registry = load_registry()
    for student in sorted(classlist.all().values(), key=lambda s: s.name):
        col_name, col_mail, col_voice, col_remove = st.columns([2, 3, 3, 1])
        col_name.write(student.name)
        col_mail.write(student.email)
        voice = registry.get(student.person_id)
        if voice:
            col_voice.audio(str(ENROLLMENT_DIR / voice["audio_file"]))
        else:
            col_voice.caption("No voice sample")
        if col_remove.button("Remove", key=f"rm-{student.person_id}"):
            classlist.remove(student.person_id)
            if voice:
                (ENROLLMENT_DIR / voice["audio_file"]).unlink(missing_ok=True)
                del registry[student.person_id]
                save_registry(registry)
            st.rerun()

# --- Session workspace -----------------------------------------------------------------------

else:
    inputs = records.inputs(session_id)
    meta = by_id[session_id]
    latest = records.latest_draft(session_id)
    st.caption("CLASS SESSION / " + inputs.courseTitle)
    st.title(inputs.sessionTitle)
    st.caption(
        f"{when(meta['created_at'])} · {len(inputs.roster)} students · {inputs.rubric.title}"
    )
    step = st.segmented_control(
        "Session steps",
        ["Record", "Who spoke?", "AI assessment", "Approve", "Send"],
        key="step",
        default=None if "step" in st.session_state else "AI assessment",
        selection_mode="single",
        required=True,
        bind="query-params",
        width="stretch",
    )
    st.divider()
    if step == "Record":
        st.subheader("Class recording")
        recording = DATA_DIR / "recordings" / f"{session_id}.wav"
        if recording.exists():
            st.audio(str(recording))
        else:
            st.info(
                "This session has no saved recording. Its reviewed transcript is in Who spoke?."
            )
        st.button("Record a new session", on_click=go, args=("new",))
    elif step == "Who spoke?":
        listener_view(records, session_id, inputs)
    elif step == "AI assessment":
        live = live_runs().get(session_id)
        running = bool(live and live["thread"].is_alive())
        tabs = st.tabs(TABS, key="agent", on_change="rerun", bind="query-params")
        for name, tab in zip(TABS, tabs, strict=True):
            if not tab.open:
                continue
            with tab:

                def agent_panel(name=name):
                    if name == "Overview":
                        overview(records, session_id, inputs, live_runs().get(session_id))
                    else:
                        render_agent(name, records, session_id, inputs, live_runs().get(session_id))
                    entry = live_runs().get(session_id)
                    if entry and entry["ended"] and not entry.get("reported"):
                        entry["reported"] = True
                        st.rerun()

                st.fragment(run_every=2 if running else None)(agent_panel)()
                if name == "Overview":
                    a, b, _ = st.columns([1, 1, 2])
                    if a.button(
                        "Assessment running…"
                        if running
                        else "Generate assessment"
                        if latest is None
                        else "Regenerate assessment",
                        type="primary",
                        disabled=running,
                        width="stretch",
                    ):
                        start_run(session_id)
                        st.rerun()
                    if (
                        latest is None
                        and not running
                        and b.button("Write it myself", width="stretch")
                    ):
                        records.create_professor_draft(session_id)
                        st.rerun()
                if name == "Evidence / Research":
                    with st.expander("Ask the course notes"):
                        st.write(
                            "Ask the evidence agent to check something said in class against "
                            "the course "
                            "documents. It chooses its own searches and must cite exact "
                            "excerpts; it never scores."
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
                            format_func=turn_labels.get,
                            max_selections=8,
                        )
                        crit = {c.id: c.title for c in inputs.rubric.criteria}
                        criterion_ids = st.multiselect(
                            "Rubric criteria",
                            list(crit),
                            format_func=crit.get,
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
                                        icon = "✅" if a["outcome"] == "ok" else "⛔"
                                        log.write(f"{icon} `{a['tool']}`: {a['summary']}")
                                        shown[0] += 1

                                request = Investigation(
                                    sessionId=session_id,
                                    question=question,
                                    turnIds=turn_ids,
                                    criterionIds=criterion_ids,
                                )
                                if use_research:  # ② Research (research/bridge.py), same contract
                                    from classpartai.research import bridge

                                    outcome = bridge.investigate(request, inputs, None, checkpoint)
                                else:
                                    outcome = investigate(
                                        request, inputs, driver, CourseIndex(inputs), checkpoint
                                    )
                                records.save_evidence_run(session_id, question, outcome)
                                log.update(
                                    label=(
                                        f"Evidence agent: {outcome.status} ({outcome.stopReason})"
                                    ),
                                    state="complete",
                                )
                                # Redraw after the completed evidence check.
                                st.toast("Evidence check saved in Evidence / Research")
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
                                            f"> {c['excerpt']}\n\n— {c['title']}, p. {c['page']} · "
                                            f"*{c['relationship']}*"
                                        )
                                    for g in bundle["gaps"]:
                                        st.warning(f"Gap: {g}")
                                    for c in bundle["conflicts"]:
                                        st.error(f"Conflict: {c}")
                                for a in ev["progress"]["actions"]:
                                    st.caption(f"{a['tool']} ({a['outcome']}): {a['summary']}")

    elif step in ("Approve", "Send"):
        st.subheader("Review the exact version" if step == "Approve" else "Send reviewed feedback")
        delivery_view(records, session_id, inputs)
        if step == "Approve" and latest:
            with st.expander("Edit: save a new version"):
                st.caption(
                    "Saving findings or feedback invalidates prior approvals. Invalid scores, "
                    "attribution and citations are refused."
                )
                proposal_json = json.dumps(
                    {
                        "findings": [f.model_dump() for f in latest.content.findings],
                        "feedback": [f.model_dump() for f in latest.content.feedback],
                    },
                    indent=2,
                )
                editor = st.text_area(
                    "Findings and feedback JSON", proposal_json, height=300, key=f"ed-{latest.id}"
                )
                note = st.text_input("Reason for this edit", key=f"note-{latest.id}")
                if st.button("Save new professor version", disabled=len(note.strip()) < 3):
                    try:
                        proposal = Proposal.model_validate_json(editor)
                        records.append_draft(
                            session_id, proposal, "professor", note, latest.version
                        )
                        st.rerun()
                    except (Unprocessable, ValueError) as exc:
                        st.error(str(exc))

        current = {r["student_id"]: r["email"] for r in records.recipients(session_id)}
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
                        records.set_recipient(session_id, s.id, email)
                        st.rerun()
                    except Unprocessable as exc:
                        st.error(str(exc))

        if latest is None:
            st.info(
                "Generate an assessment (or write it yourself) in AI assessment before approving."
            )
        else:
            approval = records.active_approval(session_id)
            if approval:
                note = approval["acknowledgement"] or "no issues"
                st.success(f"Version {latest.version} approved by {approval['approver']}: {note}")
            elif step == "Approve":
                ack = st.checkbox(
                    f"I reviewed version {latest.version}, its evidence, "
                    "gaps and unresolved issues.",
                    key=f"ack-{latest.id}",
                )
                col_why, col_who = st.columns([3, 1])
                reason = col_why.text_input(
                    "Acknowledgement / override reason (needed if issues remain)",
                    key=f"why-{latest.id}",
                )
                approver = col_who.text_input("Approving as", "Prof (demo)")
                if st.button(f"Approve version {latest.version}", type="primary"):
                    try:
                        records.approve_draft(session_id, latest.id, ack, reason, approver)
                        st.rerun()
                    except Unprocessable as exc:
                        st.error(str(exc))
                st.caption("Approval is separate from sending. An auditor pass is not approval.")

            if step == "Send" and st.button(
                f"Send {len(inputs.roster)} emails via AgentMail",
                type="primary" if approval else "secondary",
                disabled=approval is None,
            ):
                transport = AgentMailTransport(
                    os.getenv("AGENTMAIL_API_KEY", ""), os.getenv("AGENTMAIL_INBOX", "")
                )
                try:
                    results = deliver_approved(
                        records, session_id, approval["id"], transport, DeliverySettings.from_env()
                    )
                    st.toast(", ".join(f"{r['studentId']}: {r['state']}" for r in results))
                except Unprocessable as exc:
                    st.error(str(exc))
            st.caption(
                "Accepted means AgentMail accepted it, not confirmed inbox delivery. Accepted "
                "messages are never resent; ambiguous outcomes are never retried automatically."
            )
            deliveries = records.deliveries(session_id)
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
