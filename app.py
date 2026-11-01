"""Streamlit demo for ClassPart AI. Run with `uv run streamlit run app.py`.

Analyse: a recording (or the sample session) runs Listener -> Research -> Judge -> Auditor,
then the Action agent drafts feedback. Feedback emails: the prof approves or rejects each
draft here; approved ones are sent through AgentMail. Class list: names, emails, voice samples.
"""

import json
import os
import subprocess
import tempfile
import threading
import time
from datetime import date
from pathlib import Path

import streamlit as st

from classpartai.action.agent import ActionAgent
from classpartai.action.harness import GuardrailError, Harness, Settings
from classpartai.action.mailer import AgentMailMailer
from classpartai.action.store import Store
from classpartai.agents import listener
from classpartai.classlist import ClassList, person_id_for
from classpartai.config import DATA_DIR, ENROLLMENT_DIR, REPO_ROOT
from classpartai.contracts import SessionResults
from classpartai.orchestrator import STAGES, score_session
from classpartai.ui import board_html, flow_html

REGISTRY_PATH = ENROLLMENT_DIR / "registry.json"
SAMPLE_SESSION = REPO_ROOT / "data" / "sample_session.json"
SAMPLE_CLASSLIST = REPO_ROOT / "data" / "sample_classlist.json"
AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "flac", "webm"]


# --- Shared state ---------------------------------------------------------------------------


@st.cache_resource
def services() -> tuple[Store, ClassList, Harness]:
    store, classlist = Store(DATA_DIR / "classpartai.db"), ClassList(DATA_DIR / "classlist.json")
    mailer = AgentMailMailer(os.getenv("AGENTMAIL_API_KEY", ""), os.getenv("AGENTMAIL_INBOX", ""))
    return store, classlist, Harness(store, classlist, mailer, Settings.from_env())


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


store, classlist, harness = services()

st.set_page_config(page_title="ClassPart AI")
st.title("ClassPart AI")
st.caption("Class participation, transcribed, scored and fed back.")

analyse_tab, emails_tab, class_tab = st.tabs(["Analyse", "Feedback emails", "Class list"])

# --- Analyse ---------------------------------------------------------------------------------

REPLAY_DELAY = 0.25  # seconds per stage step when replaying the pre-scored sample session


def placeholder_stages() -> set[str]:
    return {name for name, mod in STAGES.items() if mod.IS_PLACEHOLDER}


def show_flow(slot, flow: dict) -> None:
    """Redraw the pipeline strip from ``flow`` = {active, done, notes}."""
    with slot.container():
        # Names are escaped in classpartai.ui, so this HTML holds no untrusted markup.
        st.iframe(
            flow_html(flow["active"], flow["done"], placeholder_stages(), flow["notes"]), height=118
        )


def show_board(slot, board: dict, newest: str | None = None) -> None:
    with slot.container():
        cards = [(name, " ".join(sorted(states))) for name, states in board.items()]
        rows = -(-len(cards) // 4)  # ceil: roughly four cards per row
        st.iframe(board_html(cards, newest), height=40 + 70 * max(rows, 1))


with analyse_tab:
    col_course, col_date, col_topic = st.columns([2, 1, 2])
    course = col_course.text_input("Course", "IS469 Gen AI with LLMs")
    session_date = col_date.date_input("Date", date.today())
    topic = col_topic.text_input("Topic", "")

    recording = st.file_uploader("Class recording", type=AUDIO_TYPES)
    col_run, col_sample = st.columns(2)
    run_recording = recording and col_run.button("Analyse recording", type="primary")
    run_sample = col_sample.button("Use the sample session")

    flow = st.session_state.setdefault("flow", {"active": None, "done": set(), "notes": {}})
    flow_slot = st.empty()
    show_flow(flow_slot, flow)

    def step(stage: str, note: str = "", finished: str | None = None, pause: float = 0) -> None:
        """Mark ``stage`` active (with a note), optionally mark ``finished`` done, then redraw."""
        if finished:
            flow["done"].add(finished)
        flow["active"] = stage
        if note:
            flow["notes"][stage] = note
        show_flow(flow_slot, flow)
        if pause:
            time.sleep(pause)

    def reset_flow() -> None:
        flow.update(active=None, done=set(), notes={})
        st.session_state.pop("agent_run", None)
        st.session_state.pop("board", None)

    if run_recording:
        reset_flow()
        step("listener", "transcribing…")
        if not REGISTRY_PATH.exists():
            save_registry({})
        process_audio, lock = load_listener()
        with tempfile.TemporaryDirectory() as tmp, lock:
            result = process_audio(str(to_wav(recording, Path(tmp) / "recording.wav")))
        session_id = f"{session_date.isoformat()}-{person_id_for(topic or 'class')}"
        ids_by_name = {p["name"]: pid for pid, p in load_registry().items()}
        contributions = listener.to_contributions(result, session_id, ids_by_name)
        flow["notes"]["listener"] = f"{len(contributions)} turns"
        flow["done"].add("listener")

        def on_progress(stage: str, n: int, total: int) -> None:
            step(stage, f"{n}/{total}")

        session = score_session(
            contributions, session_id, course, session_date.isoformat(), topic, on_progress
        )
        flow["done"].update({"research", "judge", "auditor"})
        flow["active"] = None
        show_flow(flow_slot, flow)
        st.session_state.session = session

    if run_sample:
        reset_flow()
        for pid, entry in json.loads(SAMPLE_CLASSLIST.read_text()).items():
            if classlist.get(pid) is None:
                classlist.upsert(entry["name"], entry["email"])
        session = SessionResults.model_validate_json(SAMPLE_SESSION.read_text())
        step("listener", "loading sample…", pause=REPLAY_DELAY * 2)
        flow["notes"]["listener"] = f"{len(session.items)} turns (sample)"
        flow["done"].add("listener")
        scored = [i for i in session.items if i.judgement]
        for n, _ in enumerate(scored, start=1):
            for stage in ("research", "judge", "auditor"):
                step(stage, f"{n}/{len(scored)}", pause=REPLAY_DELAY)
        flow["done"].update({"research", "judge", "auditor"})
        flow["active"] = None
        show_flow(flow_slot, flow)
        st.session_state.session = session

    session: SessionResults | None = st.session_state.get("session")
    if session:
        st.subheader(f"Session {session.session_id}")
        if session.placeholder_stages:
            stages = ", ".join(session.placeholder_stages)
            st.warning(f"Placeholder stages (not built yet): {stages}. Scores are not real.")
        rows = []
        for item in session.items:
            c = item.contribution
            rows.append(
                {
                    "Time": f"{c.start:.0f}s",
                    "Speaker": c.speaker,
                    "Said": c.text,
                    "Score": item.judgement.overall if item.judgement else None,
                    "Audit": item.audit.verdict if item.audit else "not scored",
                }
            )
        st.dataframe(rows, hide_index=True, width="stretch")

        st.subheader("Action agent")
        board_slot = st.empty()
        names = {s.person_id: s.name for s in classlist.all().values()}

        if not os.getenv("OPENAI_API_KEY"):
            st.error("Set OPENAI_API_KEY to run the Action agent.")
        elif st.button("Run Action agent", type="primary"):
            board = {name: {"waiting"} for name in sorted(names.values())}
            show_board(board_slot, board)
            status = st.status("The Action agent is working…", expanded=True)
            counter = {"calls": 0}

            def on_event(kind: str, call) -> None:
                if kind == "thinking":
                    step("action", f"thinking… ({counter['calls']} calls)", finished="auditor")
                    return
                if kind == "done":
                    for states in board.values():
                        if states == {"waiting"}:
                            states.clear()
                            states.add("nothing")
                    flow["done"].add("action")
                    flow["active"] = None
                    flow["notes"]["action"] = f"{counter['calls']} tool calls"
                    show_flow(flow_slot, flow)
                    show_board(board_slot, board)
                    return
                counter["calls"] += 1
                args = call.arguments
                status.write(
                    f"{'✅' if call.ok else '⛔'} `{call.name}` "
                    + (
                        f"→ {names.get(args.get('person_id'), args.get('person_id'))}"
                        if args.get("person_id")
                        else ""
                    )
                )
                if not call.ok:
                    status.caption(json.loads(call.result).get("refused", call.result))
                    return
                who = names.get(args.get("person_id"))
                if call.name == "draft_student_email" and who:
                    board[who].discard("waiting")
                    board[who].add(args["kind"])
                elif call.name == "flag_for_review":
                    who = who or "Unidentified speaker"
                    board.setdefault(who, set()).discard("waiting")
                    board[who].add("flagged")
                elif call.name == "send_prof_summary":
                    who = "Prof summary"
                    board[who] = {"summary"}
                else:
                    return
                show_board(board_slot, board, newest=who)

            run = ActionAgent(harness).run(session, on_event)
            status.update(label="The Action agent finished", state="complete", expanded=False)
            st.session_state.agent_run = run
            st.session_state.board = board

        run = st.session_state.get("agent_run")
        if run:
            if "board" in st.session_state:
                show_board(board_slot, st.session_state.board)
            with st.expander(f"Tool calls ({len(run.calls)})"):
                for call in run.calls:
                    icon = "✅" if call.ok else "⛔"
                    st.markdown(f"{icon} **{call.name}**")
                    st.json({"arguments": call.arguments, "result": json.loads(call.result)})
            st.info(run.final_message or "The agent finished without a summary.")
            st.write("Review the drafts on the **Feedback emails** tab.")

# --- Feedback emails -------------------------------------------------------------------------

with emails_tab:
    settings = harness.settings
    if settings.test_mode:
        st.info(f"Test mode: every email is sent to {settings.test_recipient or '(not set)'}.")
    approver = st.text_input("Approving as", "Prof (demo)")
    names = {s.person_id: s.name for s in classlist.all().values()}

    pending = store.emails("pending")
    st.subheader(f"Waiting for approval ({len(pending)})")
    if pending and st.button("Approve and send all"):
        for email in pending:
            try:
                harness.approve(email.id, approver)
            except GuardrailError as exc:
                st.error(f"Email {email.id}: {exc}")
        st.rerun()

    for email in pending:
        label = f"{email.kind} → {names.get(email.person_id, email.person_id)} ({email.recipient})"
        with st.expander(label, expanded=True):
            subject = st.text_input("Subject", email.subject, key=f"subj-{email.id}")
            body = st.text_area("Body", email.body, height=220, key=f"body-{email.id}")
            col_ok, col_no = st.columns(2)
            if col_ok.button("Approve and send", key=f"ok-{email.id}", type="primary"):
                try:
                    sent = harness.approve(email.id, approver, subject, body)
                    st.toast(f"Email {email.id}: {sent.status}")
                except GuardrailError as exc:
                    st.error(str(exc))
                st.rerun()
            if col_no.button("Reject", key=f"no-{email.id}"):
                harness.reject(email.id, approver)
                st.rerun()

    flags = store.flags()
    if flags:
        st.subheader(f"Flagged for review ({len(flags)})")
        st.dataframe(
            [
                {
                    "Session": f["session_id"],
                    "Student": names.get(f["person_id"], f["person_id"] or "unidentified"),
                    "Contribution": f["contribution_id"],
                    "Reason": f["reason"],
                }
                for f in flags
            ],
            hide_index=True,
            width="stretch",
        )

    done = [e for e in store.emails() if e.status != "pending"]
    if done:
        st.subheader("History")
        st.dataframe(
            [
                {
                    "Kind": e.kind,
                    "To": e.recipient,
                    "Delivered to": e.sent_to,
                    "Status": e.status,
                    "By": e.decided_by,
                    "When": e.decided_at,
                    "Subject": e.subject,
                    "Error": e.error,
                }
                for e in reversed(done)
            ],
            hide_index=True,
            width="stretch",
        )

# --- Class list ------------------------------------------------------------------------------

with class_tab:
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
