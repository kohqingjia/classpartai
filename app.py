"""Streamlit demo for ClassPart AI. Run with `uv run streamlit run app.py`.

The Listener stage comes from audio-service/ (CPA-18/19/20): transcribe, diarise, and identify
each speaker against the voice samples registered on the "Voice samples" tab.
"""

import json
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import streamlit as st

AUDIO_SERVICE = Path(__file__).resolve().parent / "audio-service"
ENROLLMENT_DIR = AUDIO_SERVICE / "enrollments"
REGISTRY_PATH = ENROLLMENT_DIR / "registry.json"
AUDIO_TYPES = ["wav", "mp3", "m4a", "ogg", "flac", "webm"]


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        return {}
    return json.loads(REGISTRY_PATH.read_text())


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


@st.cache_resource(show_spinner="Loading speech models (the first run downloads them)…")
def load_listener():
    """Import the pipeline once per server; its modules load the models at import time."""
    sys.path.insert(0, str(AUDIO_SERVICE))
    from pipeline import process_audio

    # The pipeline writes per-speaker clips to a shared folder, so run one recording at a time.
    return process_audio, threading.Lock()


st.set_page_config(page_title="ClassPart AI")
st.title("ClassPart AI")
st.caption("Class participation, transcribed and attributed to each speaker.")

analyse_tab, samples_tab = st.tabs(["Analyse recording", "Voice samples"])

with analyse_tab:
    registry = load_registry()
    if not registry:
        st.info("No voice samples yet, so every speaker will show as UNKNOWN. Add some first.")

    recording = st.file_uploader("Class recording", type=AUDIO_TYPES, key="recording")
    if recording and st.button("Analyse", type="primary"):
        if not REGISTRY_PATH.exists():
            save_registry({})
        process_audio, lock = load_listener()
        with tempfile.TemporaryDirectory() as tmp, lock:
            with st.spinner("Transcribing, diarising and identifying speakers…"):
                result = process_audio(str(to_wav(recording, Path(tmp) / "recording.wav")))

        st.subheader("Speakers")
        identities = result["speaker_identities"].items()
        st.table([{"Diarised label": k, "Identified as": v} for k, v in identities])
        st.subheader("Transcript")
        for seg in result["segments"]:
            when = f"{seg['start']:.1f}s–{seg['end']:.1f}s"
            st.markdown(f"`{when}` **{seg['speaker']}**: {seg['text']}")

with samples_tab:
    st.write(
        "Register each student with a clear 20–30 second clip of them speaking alone. "
        "Only register people who have agreed to it."
    )
    registry = load_registry()

    with st.form("enrol", clear_on_submit=True):
        name = st.text_input("Name")
        sample = st.file_uploader("Voice sample", type=AUDIO_TYPES)
        if st.form_submit_button("Add sample") and name.strip() and sample:
            person_id = re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")
            ENROLLMENT_DIR.mkdir(parents=True, exist_ok=True)
            to_wav(sample, ENROLLMENT_DIR / f"{person_id}.wav")
            registry[person_id] = {"name": name.strip(), "audio_file": f"{person_id}.wav"}
            save_registry(registry)
            st.success(f"Added {name.strip()}.")

    for person_id, person in sorted(registry.items()):
        col_name, col_audio, col_remove = st.columns([2, 4, 1])
        col_name.write(person["name"])
        col_audio.audio(str(ENROLLMENT_DIR / person["audio_file"]))
        if col_remove.button("Remove", key=f"rm-{person_id}"):
            (ENROLLMENT_DIR / person["audio_file"]).unlink(missing_ok=True)
            del registry[person_id]
            save_registry(registry)
            st.rerun()
