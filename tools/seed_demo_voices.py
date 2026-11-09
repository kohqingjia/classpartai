"""Enrol the demo speakers on this machine, so the demo seminars can go through the Listener.

    uv run python tools/seed_demo_voices.py

Copies each clip in data/voice-samples/ (not in git: copy them there from the server) into
audio-service/enrollments and adds the person to the class list (var/classlist.json) with a
placeholder email. Names match the speakers in the demo
seminar scripts. In email test mode every message goes to one inbox, so the placeholders are
never used. People already enrolled are left alone.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classpartai.classlist import ClassList, person_id_for  # noqa: E402
from classpartai.config import DATA_DIR, ENROLLMENT_DIR  # noqa: E402
from classpartai.voices import Voices  # noqa: E402

PEOPLE = {
    "prof": ("Prof Wynter", "professor"),
    "koh-qing-jia": ("Koh Qing Jia", "student"),
    "le-yong": ("Le Yong", "student"),
    "tasmin": ("Tasmin", "student"),
    "tina": ("Tina", "student"),
}


def main() -> None:
    voices, classlist = Voices(ENROLLMENT_DIR), ClassList(DATA_DIR / "classlist.json")
    for stem, (name, role) in PEOPLE.items():
        clip = ROOT / "data" / "voice-samples" / f"{stem}.wav"
        person_id = person_id_for(name)
        if classlist.get(person_id) is None:  # never overwrite a real person's email
            classlist.upsert(name, f"{stem}@example.edu", role)
        if voices.get(person_id) or not clip.exists():
            print(f"{name}: {'already enrolled' if voices.get(person_id) else 'no clip found'}")
            continue
        check = voices.enrol(person_id, name, clip)
        print(f"{name} ({role}): enrolled, {check.seconds:.0f} s")
    print(f"Voices in {ENROLLMENT_DIR}; class list in {DATA_DIR / 'classlist.json'}")


if __name__ == "__main__":
    main()
