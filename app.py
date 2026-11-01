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
from classpartai.orchestrator import score_session

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

with analyse_tab:
    col_course, col_date, col_topic = st.columns([2, 1, 2])
    course = col_course.text_input("Course", "IS469 Gen AI with LLMs")
    session_date = col_date.date_input("Date", date.today())
    topic = col_topic.text_input("Topic", "")

    recording = st.file_uploader("Class recording", type=AUDIO_TYPES)
    col_run, col_sample = st.columns(2)

    if recording and col_run.button("Analyse recording", type="primary"):
        if not REGISTRY_PATH.exists():
            save_registry({})
        process_audio, lock = load_listener()
        with tempfile.TemporaryDirectory() as tmp, lock:
            with st.spinner("Transcribing, diarising and identifying speakers…"):
                result = process_audio(str(to_wav(recording, Path(tmp) / "recording.wav")))
        session_id = f"{session_date.isoformat()}-{person_id_for(topic or 'class')}"
        ids_by_name = {p["name"]: pid for pid, p in load_registry().items()}
        contributions = listener.to_contributions(result, session_id, ids_by_name)
        st.session_state.session = score_session(
            contributions, session_id, course, session_date.isoformat(), topic
        )

    if col_sample.button("Use the sample session"):
        for pid, entry in json.loads(SAMPLE_CLASSLIST.read_text()).items():
            if classlist.get(pid) is None:
                classlist.upsert(entry["name"], entry["email"])
        st.session_state.session = SessionResults.model_validate_json(SAMPLE_SESSION.read_text())

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

        if not os.getenv("OPENAI_API_KEY"):
            st.error("Set OPENAI_API_KEY to run the Action agent.")
        elif st.button("Run Action agent", type="primary"):
            with st.spinner("The Action agent is deciding who to email…"):
                run = ActionAgent(harness).run(session)
            st.session_state.agent_run = run

        run = st.session_state.get("agent_run")
        if run:
            st.subheader("What the Action agent did")
            for call in run.calls:
                icon = "✅" if call.ok else "⛔"
                with st.expander(f"{icon} {call.name}({', '.join(call.arguments)})"):
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
