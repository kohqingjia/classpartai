"""Make the synthetic demo recording (data/demo_audio) with macOS's built-in voices.

The demo seminar's transcript (data/sample_assessment.json) read by a different voice per person,
plus an enrolment clip per person, so the recording path can be shown without anyone recording.
The unknown speaker uses a voice that is never enrolled, and Marcus is enrolled but silent, as in
the sample. Needs macOS `say` and ffmpeg with libopus. Run: `python scripts/make_demo_audio.py`.
"""

import json
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "demo_audio"
SAMPLE = json.loads((ROOT / "data" / "sample_assessment.json").read_text())

PEOPLE = [  # person_id, registered name, role, macOS voice
    ("demo-professor", "Prof Demo", "professor", "Samantha"),
    ("alex-tan", "Alex Tan", "student", "Daniel"),
    ("priya-nair", "Priya Nair", "student", "Karen"),
    ("jordan-wong", "Jordan Wong", "student", "Rishi"),
    ("marcus-lee", "Marcus Lee", "student", "Fred"),
]
UNKNOWN_VOICE = "Tessa"  # never enrolled: their turn must come out as an unknown speaker
ENROL_TEXT = (
    "Hello, this is my voice sample for the seminar. I usually read the slides before class, "
    "try the lab exercises, and write down questions about retrieval, embeddings and evaluation "
    "so I can ask them during the discussion. This recording helps the system recognise me."
)


def say(voice: str, text: str, dest: Path) -> None:
    subprocess.run(["say", "-v", voice, "-o", str(dest), text], check=True)


def to_opus(sources: list[Path], dest: Path, gap: float = 0.8) -> None:
    """Concatenate clips with `gap` seconds of silence between them, as 16 kHz mono Opus."""
    inputs, parts = [], []
    for i, src in enumerate(sources):
        inputs += ["-i", str(src)]
        parts.append(
            f"[{i}:a]aresample=16000,aformat=channel_layouts=mono,apad=pad_dur={gap}[a{i}]"
        )
    joined = "".join(f"[a{i}]" for i in range(len(sources)))
    graph = ";".join(parts) + f";{joined}concat=n={len(sources)}:v=0:a=1[out]"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            graph,
            "-map",
            "[out]",
            "-c:a",
            "libopus",
            "-b:a",
            "32k",
            str(dest),
        ],
        check=True,
    )


def main() -> None:
    voices = {pid: voice for pid, _, _, voice in PEOPLE}
    (OUT / "voices").mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        for pid, _, _, voice in PEOPLE:
            say(voice, ENROL_TEXT, tmp / f"{pid}.aiff")
            to_opus([tmp / f"{pid}.aiff"], OUT / "voices" / f"{pid}.ogg", gap=0)
        lines = []
        for n, turn in enumerate(SAMPLE["transcript"]["turns"]):
            speaker = turn["speaker"]
            voice = (
                voices["demo-professor"]
                if speaker["kind"] == "professor"
                else voices[speaker["studentId"]]
                if speaker["kind"] == "student"
                else UNKNOWN_VOICE
            )
            say(voice, turn["text"], tmp / f"turn-{n}.aiff")
            lines.append(tmp / f"turn-{n}.aiff")
        to_opus(lines, OUT / "seminar.ogg")
    manifest = {
        "seminar": "seminar.ogg",
        "people": [
            {"personId": pid, "name": name, "role": role, "file": f"voices/{pid}.ogg"}
            for pid, name, role, _ in PEOPLE
        ],
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
