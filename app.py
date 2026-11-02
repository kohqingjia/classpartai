"""Streamlit app for ClassPart AI. Run with `uv run streamlit run app.py`.

The workflow follows Le Yong's design (feat/assessment-foundation), ported to Python:
Session (reviewed transcript + roster + rubric + course documents) -> Evidence -> Assessment
(the coordinator agent drafts findings and feedback) -> professor approval of the exact version
-> delivery through AgentMail. Recordings come in through Tina's Listener pipeline.

The layout borrows from Notion's AI meeting notes: each class session is one page, with the
recording, transcript and AI summary in a single card and review & send underneath.
"""

import json
import os
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import streamlit as st

from classpartai.agents import listener
from classpartai.assessment import AssessmentInputs, parse_inputs
from classpartai.classlist import ClassList
from classpartai.config import DATA_DIR, ENROLLMENT_DIR, REPO_ROOT
from classpartai.evidence import INSTRUCTIONS as EVIDENCE_INSTRUCTIONS
from classpartai.evidence import TOOL_DEFINITIONS as EVIDENCE_TOOLS
from classpartai.evidence import CourseIndex, Investigation, investigate
from classpartai.models import configured_driver
from classpartai.participation.coordinator import coordinate
from classpartai.participation.delivery import (
    AgentMailTransport,
    DeliverySettings,
    deliver_approved,
)
from classpartai.participation.records import Records
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import Unprocessable, observed_count, totals
from classpartai.ui import STAGES, TOOL_STAGE, board_html, flow_html

DATA = REPO_ROOT / "data"
REGISTRY_PATH = ENROLLMENT_DIR / "registry.json"
AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "flac", "webm"]
STAGE_NAMES = {key: name for key, _, name, _ in STAGES}
SGT = timezone(timedelta(hours=8))

# Notion-style touches Streamlit's theme can't express: left-aligned sidebar rows, a big title.
PAGE_CSS = """<style>
[data-testid="stSidebar"] button[data-testid^="stBaseButton"] > div { justify-content:flex-start; }
h1 { font-size:2.6rem !important; font-weight:700 !important; letter-spacing:-.02em; }
.muted { color:#9b9b9b; font-size:.95rem; }
</style>"""


# --- Shared state -----------------------------------------------------------------------------


@st.cache_resource
def services() -> tuple[Records, ClassList]:
    # A new file: the earlier Action-harness build left a classpartai.db with an incompatible
    # `sessions` table.
    return Records(DATA_DIR / "assessments.db"), ClassList(DATA_DIR / "classlist.json")


@st.cache_resource(show_spinner="Loading speech models (the first run downloads them)…")
def load_listener():
    # The pipeline writes per-speaker clips to a shared folder, so run one recording at a time.
    return listener.load_pipeline(), threading.Lock()


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
    st.session_state.view = view
    if session:
        st.session_state.session_id = session


def show_flow(slot, active=None, done=(), notes=None, banner="") -> None:
    with slot.container():
        # Dynamic strings are escaped in classpartai.ui or below, so there's no untrusted markup.
        st.iframe(flow_html(active, set(done), set(), notes or {}, banner), height=165)


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

st.set_page_config(page_title="ClassPart AI", page_icon="🎓", layout="wide")
st.html(PAGE_CSS)

# --- Sidebar: like Notion's meeting list ------------------------------------------------------

sessions = records.sessions()
by_id = {s["id"]: s for s in sessions}
if "view" not in st.session_state:
    st.session_state.view = "session" if sessions else "new"
if st.session_state.get("session_id") not in by_id:
    st.session_state.session_id = next(iter(by_id), None)
if st.session_state.view == "session" and not sessions:
    st.session_state.view = "new"

with st.sidebar:
    st.markdown("### 🎓 ClassPart AI")
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
        "👥 Class list",
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

view = st.session_state.view
session_id = st.session_state.session_id


def open_session(new_inputs: AssessmentInputs) -> None:
    new_id = records.create_session(new_inputs)
    n = set_recipients_from_classlist(new_id, new_inputs)
    go("session", new_id)
    st.toast(f"Session created; {n} recipient(s) filled from the class list.")
    st.rerun()


# --- New class session ------------------------------------------------------------------------

if view == "new":
    roster = list(classlist.all().values())
    st.session_state.setdefault("new-title", default_title())
    st.title(st.session_state["new-title"] or "Untitled session")
    col_title, col_course = st.columns(2)
    title = col_title.text_input("Title", key="new-title")
    course = col_course.text_input("Course", "IS469 Gen AI with LLMs")

    with st.container(border=True):
        st.markdown("**🎙️ Class recording**")
        if not roster:
            st.warning("Add students on the Class list first, so the recording has a roster.")
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
            process_audio, lock = load_listener()
            with tempfile.TemporaryDirectory() as tmp, lock:
                with st.spinner("Transcribing, diarising and identifying speakers…"):
                    result = process_audio(str(to_wav(audio, Path(tmp) / "rec.wav")))
            ids = {p["name"]: pid for pid, p in load_registry().items()}
            st.session_state.pending_transcript = listener.to_transcript(result, ids, "review-1")
            st.session_state.pending_meta = (title, course)

        pending = st.session_state.get("pending_transcript")
        if pending:
            st.divider()
            st.markdown("**Transcript: check who said what before it's used**")
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
                        documents=json.loads((DATA / "course_materials.json").read_text()),
                    )
                )

    st.markdown('<p class="muted">No recording to hand?</p>', unsafe_allow_html=True)
    col_demo, col_fixture, _ = st.columns([1, 1, 2])
    if col_demo.button("▶ Use the demo seminar", width="stretch"):
        for pid, entry in json.loads((DATA / "sample_classlist.json").read_text()).items():
            if classlist.get(pid) is None:
                classlist.upsert(entry["name"], entry["email"])
        open_session(parse_inputs((DATA / "sample_assessment.json").read_text()))
    if col_fixture.button("Use Le Yong's fixture", width="stretch"):
        open_session(parse_inputs((DATA / "fixture-fictional.json").read_text()))
    with st.expander("Import a session file (JSON)"):
        st.caption("A reviewed session file: roster, transcript, rubric and course documents.")
        upload = st.file_uploader("Session JSON", type=["json"])
        if upload and st.button("Import", type="primary"):
            try:
                open_session(parse_inputs(upload.getvalue().decode()))
            except ValueError as exc:
                st.error(str(exc))

# --- Class list -------------------------------------------------------------------------------

elif view == "classlist":
    st.title("Class list")
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

# --- Session page -----------------------------------------------------------------------------

else:
    inputs = records.inputs(session_id)
    meta = by_id[session_id]
    latest = records.latest_draft(session_id)
    st.title(inputs.sessionTitle)
    st.markdown(
        f'<p class="muted">📅 {escape(when(meta["created_at"]))} · {escape(inputs.courseTitle)} · '
        f"{len(inputs.roster)} students · {escape(inputs.rubric.title)}</p>",
        unsafe_allow_html=True,
    )

    with st.container(border=True):
        tab_summary, tab_transcript, tab_evidence, tab_details = st.tabs(
            ["✨ Summary", "💬 Transcript", "🔎 Ask the course notes", "⋯ Details"]
        )

    # Summary: the coordinator's run and its result.
    with tab_summary:
        flow_slot, board_slot = st.empty(), st.empty()
        if latest is None:
            st.markdown(
                '<p class="muted">ClassPart AI will check what was said against the course '
                "notes, score each student against the rubric, audit those scores and draft "
                "feedback for each student. Nothing is sent until you approve it.</p>",
                unsafe_allow_html=True,
            )
        show_flow(flow_slot, banner="<b>Coordinator</b> idle")
        show_board(board_slot, student_cards(inputs, latest))
        col_run, col_blank, _ = st.columns([1, 1, 2])
        run = col_run.button(
            "✨ Generate summary" if latest is None else "✨ Regenerate",
            type="primary",
            width="stretch",
        )
        if run:
            log = st.status("The coordinator is working…", expanded=True)
            state = {"done": set(), "notes": {}, "counts": {}, "refused": {}}

            def on_event(kind, detail):
                if kind == "thinking":
                    show_flow(
                        flow_slot,
                        None,
                        state["done"],
                        state["notes"],
                        "<b>Coordinator</b> thinking…",
                    )
                    return
                if kind == "done":
                    reason = escape(detail["stopReason"].replace("_", " "))
                    show_flow(
                        flow_slot, None, state["done"], state["notes"], f"<b>Finished</b>: {reason}"
                    )
                    show_board(board_slot, student_cards(inputs, records.latest_draft(session_id)))
                    return
                stage = TOOL_STAGE.get(detail["tool"])
                ok = detail["outcome"] == "ok"
                log.write(f"{'✅' if ok else '⛔'} `{detail['tool']}`: {detail['summary']}")
                if stage:
                    state["counts"][stage] = state["counts"].get(stage, 0) + 1
                    if not ok:
                        state["refused"][stage] = state["refused"].get(stage, 0) + 1
                    note = f"{state['counts'][stage]}×"
                    if state["refused"].get(stage):
                        note += f" ({state['refused'][stage]} refused)"
                    state["notes"][stage] = note
                    if ok:
                        state["done"].add(stage)
                    banner = f"<b>Coordinator</b> chose {escape(STAGE_NAMES[stage])}"
                    show_flow(flow_slot, stage, state["done"], state["notes"], banner)
                newest = None
                if detail["tool"] == "draft_student_feedback" and ok:
                    sid = json.loads(detail["arguments"]).get("studentId")
                    newest = next((s.displayName for s in inputs.roster if s.id == sid), None)
                show_board(
                    board_slot, student_cards(inputs, records.latest_draft(session_id)), newest
                )

            try:
                coordinate(records, session_id, on_event=on_event)
                log.update(label="The coordinator finished", state="complete", expanded=False)
            except Unprocessable as exc:
                log.update(label=str(exc), state="error")
            latest = records.latest_draft(session_id)
        if latest is None and col_blank.button("Write it myself", width="stretch"):
            records.create_professor_draft(session_id)
            st.rerun()

        if latest:
            origin = "AI proposal" if latest.origin == "model" else "professor edit"
            st.markdown(f"#### Version {latest.version} · {origin}")
            st.caption(latest.content.revisionNote)
            bundles = dict(records.evidence_for(session_id))
            criteria = {c.id: c.title for c in inputs.rubric.criteria}
            turns = {t.id: t for t in inputs.transcript.turns}
            for s in inputs.roster:
                total = totals(latest.content, inputs, s.id)
                headline = (
                    f"{total['total']:g}/{total['maximum']}"
                    if total["total"] is not None
                    else f"{total['assessedCriteria']}/{total['totalCriteria']} criteria assessed"
                )
                with st.expander(f"**{s.displayName}** · {headline}"):
                    fb = next((x for x in latest.content.feedback if x.studentId == s.id), None)
                    if fb:
                        st.markdown(f"{fb.strengths}\n\n**Next step:** {fb.nextStep}")
                        if fb.limitations:
                            st.caption("Limitations: " + "; ".join(fb.limitations))
                    else:
                        st.warning("No feedback draft yet; every roster student needs one.")
                    st.caption(
                        f"Observed attributed contributions: {observed_count(inputs, s.id)} "
                        f"(counts are separate from judgement). {total['limitation']}."
                    )
                    for f in [x for x in latest.content.findings if x.studentId == s.id]:
                        verdict = (
                            f"proposed {f.score:g}"
                            if f.status == "scored"
                            else "insufficient evidence, no score"
                        )
                        st.markdown(f"**{criteria[f.criterionId]}: {verdict}**")
                        st.write(f.justification)
                        if f.limitations:
                            st.caption("Limitations: " + "; ".join(f.limitations))
                        for tid in f.turnIds:
                            st.caption(f"{tid}: {turns[tid].text}")
                        for c in f.citations:
                            st.markdown(citation_text(bundles, c))

            issues = latest.content.audit.issues
            audited = (
                "Model audit completed; professor approval still required"
                if latest.content.audit.modelReviewed
                else "Model audit pending; explicit professor acknowledgement required"
            )
            with st.expander(f"Audit and uncertainty · {len(issues)} issue(s)"):
                st.caption(audited)
                for i in issues:
                    resolution = f": {i.resolution}" if i.resolution else ""
                    text = f"**{i.severity}** · {i.detail} ({i.disposition}{resolution})"
                    (st.error if i.severity == "blocking" else st.warning)(text)

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

    with tab_transcript:
        st.caption(
            f"Reviewed transcript {inputs.transcript.version} · {len(inputs.transcript.turns)} "
            "turns. Greyed-out turns have an uncertain speaker and are never scored."
        )
        show_transcript(inputs.transcript.turns, {s.id: s.displayName for s in inputs.roster})

    with tab_evidence:
        st.write(
            "Ask the evidence agent to check something said in class against the course "
            "documents. It chooses its own searches and must cite exact excerpts; it never scores."
        )
        question = st.text_input(
            "Question", placeholder="Is Alex's latency point supported by the notes?"
        )
        turn_labels = {
            t.id: f"{t.id} · {speaker_name(inputs, t)}: {t.text[:60]}"
            for t in inputs.transcript.turns
        }
        turn_ids = st.multiselect(
            "Turns (1–8)", list(turn_labels), format_func=turn_labels.get, max_selections=8
        )
        crit = {c.id: c.title for c in inputs.rubric.criteria}
        criterion_ids = st.multiselect(
            "Rubric criteria", list(crit), format_func=crit.get, default=list(crit)[:1]
        )
        ready = bool(len(question.strip()) >= 5 and turn_ids and criterion_ids)
        if st.button("Investigate", type="primary", disabled=not ready):
            driver = configured_driver(EVIDENCE_INSTRUCTIONS, EVIDENCE_TOOLS)
            if driver is None:
                st.error("No model configured (set OPENAI_API_KEY).")
            else:
                log = st.status("The evidence agent is investigating…", expanded=True)
                shown = [0]

                def checkpoint(progress):
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
                outcome = investigate(request, inputs, driver, CourseIndex(inputs), checkpoint)
                records.save_evidence_run(session_id, question, outcome)
                log.update(
                    label=f"Evidence agent: {outcome.status} ({outcome.stopReason})",
                    state="complete",
                )
        for ev in records.evidence_runs(session_id):
            bundle = ev["progress"]["bundle"]
            with st.expander(f"{ev['status']} · {ev['question']}"):
                calls = ev["progress"]["modelCalls"]
                st.caption(f"Stop reason: {ev['stop_reason']} · model calls {calls}")
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

    with tab_details:
        col_r, col_c = st.columns(2)
        col_r.markdown("**Roster**")
        col_r.dataframe(
            [
                {"Student": s.displayName, "Observed turns": observed_count(inputs, s.id)}
                for s in inputs.roster
            ],
            hide_index=True,
            width="stretch",
        )
        col_c.markdown(f"**Rubric:** {inputs.rubric.title}")
        col_c.dataframe(
            [
                {"Criterion": c.title, "Range": f"{c.minScore}–{c.maxScore}"}
                for c in inputs.rubric.criteria
            ],
            hide_index=True,
            width="stretch",
        )
        docs = "; ".join(f"{d.title} ({len(d.passages)} passages)" for d in inputs.documents)
        st.caption(f"Provenance: {inputs.provenance} · Course documents: {docs}")
        st.markdown("**Version and run history**")
        for d in records.drafts(session_id):
            st.caption(f"Version {d.version} · {d.origin} · {d.content.revisionNote}")
        for r in records.runs(session_id):
            p = r["progress"]
            with st.expander(f"Run {r['status']}: {r['stop_reason'] or 'running'}"):
                st.caption(
                    f"model calls {p.get('modelCalls', 0)} · tool calls "
                    f"{p.get('toolCalls', 0)} · tokens {p.get('tokens', 0)} "
                    f"({p.get('usageKind', 'reported')})"
                )
                for a in p.get("actions", []):
                    st.caption(f"{a['tool']} ({a['outcome']}): {a['summary']}")

    # Review & send, under the card like Notion's follow-ups.
    st.markdown("### ✉️ Review & send")
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
        st.info("Generate the summary (or write it yourself) before approving.")
    else:
        approval = records.active_approval(session_id)
        if approval:
            note = approval["acknowledgement"] or "no issues"
            st.success(f"Version {latest.version} approved by {approval['approver']}: {note}")
        else:
            ack = st.checkbox(
                f"I reviewed version {latest.version}, its evidence, gaps and unresolved issues.",
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

        if st.button(
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
