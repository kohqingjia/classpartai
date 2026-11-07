"""The class list: who is in the class and their email address, keyed by person_id.

Voice samples are separate (classpartai.voices, stored in audio-service/enrollments on the
server's data volume, read by the Listener); the same person_id links a person's voice sample to
their class-list entry. The professor is on the list too (role "professor"): their voice lets the
Listener mark the professor's turns, which tell the agents what question a student answered.
"""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class Student(BaseModel):
    person_id: str
    name: str
    email: str
    role: Literal["student", "professor"] = "student"


def person_id_for(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.strip().lower()).strip("-")


class ClassList:
    def __init__(self, path: Path):
        self.path = path

    def all(self) -> dict[str, Student]:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {pid: Student(person_id=pid, **entry) for pid, entry in raw.items()}

    def get(self, person_id: str | None) -> Student | None:
        return self.all().get(person_id) if person_id else None

    def students(self) -> list[Student]:
        return [s for s in self.all().values() if s.role == "student"]

    def professors(self) -> list[Student]:
        return [s for s in self.all().values() if s.role == "professor"]

    def upsert(self, name: str, email: str, role: str = "student") -> Student:
        student = Student(
            person_id=person_id_for(name), name=name.strip(), email=email.strip(), role=role
        )
        entries = {pid: s.model_dump(exclude={"person_id"}) for pid, s in self.all().items()}
        entries[student.person_id] = student.model_dump(exclude={"person_id"})
        self._write(entries)
        return student

    def remove(self, person_id: str) -> None:
        entries = {pid: s.model_dump(exclude={"person_id"}) for pid, s in self.all().items()}
        entries.pop(person_id, None)
        self._write(entries)

    def _write(self, entries: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries, indent=2))
