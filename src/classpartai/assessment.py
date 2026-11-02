"""Assessment inputs: everything one class session is assessed from.

Ported from Le Yong's src/features/assessments/schema.ts (feat/assessment-foundation).
A session is a roster, a reviewed transcript, a rubric and the course documents the evidence
agent may search. Validation rules match the original Zod schema.
"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Id = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,80}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20000)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LearningGoal(Strict):
    id: Id
    text: Text
    approved: Literal[True]


class RosterStudent(Strict):
    id: Id
    displayName: Label


class ProfessorSpeaker(Strict):
    kind: Literal["professor"]
    label: Label


class StudentSpeaker(Strict):
    kind: Literal["student"]
    studentId: Id


class UncertainSpeaker(Strict):
    kind: Literal["uncertain"]
    label: Label
    candidateStudentIds: list[Id] = Field(max_length=10)
    reason: Text


Speaker = Annotated[
    ProfessorSpeaker | StudentSpeaker | UncertainSpeaker, Field(discriminator="kind")
]


class Turn(Strict):
    id: Id
    startMs: int = Field(ge=0)
    endMs: int = Field(ge=0)
    speaker: Speaker
    text: Text


class Transcript(Strict):
    version: Id
    reviewStatus: Literal["reviewed"]
    turns: list[Turn] = Field(min_length=1, max_length=5000)


class Criterion(Strict):
    id: Id
    title: Label
    description: Text
    kind: Literal["qualitative", "observable-participation"] | None = None
    noContributionScore: float | None = None
    requiresCourseEvidence: bool | None = None
    minScore: int = Field(ge=0, le=100)
    maxScore: int = Field(ge=0, le=100)


class Aggregation(Strict):
    method: Literal["sum"]


class Rubric(Strict):
    id: Id
    version: Id
    title: Label
    aggregation: Aggregation | None = None
    criteria: list[Criterion] = Field(min_length=1, max_length=30)


class Passage(Strict):
    id: Id
    page: int = Field(ge=1)
    text: Text


class Document(Strict):
    id: Id
    version: Id
    title: Label
    source: Label
    authorisedForCourse: Literal[True]
    passages: list[Passage] = Field(min_length=1, max_length=1000)


class AssessmentInputs(Strict):
    formatVersion: Literal[1]
    provenance: Literal["reviewed", "fictional-development"]
    courseTitle: Label
    sessionTitle: Label
    learningGoals: list[LearningGoal] | None = Field(None, max_length=20)
    roster: list[RosterStudent] = Field(min_length=1, max_length=500)
    transcript: Transcript
    rubric: Rubric
    documents: list[Document] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def check_consistency(self) -> "AssessmentInputs":
        def unique(ids: list[str], name: str) -> None:
            if len(set(ids)) != len(ids):
                raise ValueError(f"Duplicate {name} identifiers")

        unique([s.id for s in self.roster], "roster")
        unique([t.id for t in self.transcript.turns], "turn")
        unique([c.id for c in self.rubric.criteria], "criterion")
        unique([d.id for d in self.documents], "document")
        if self.learningGoals:
            unique([g.id for g in self.learningGoals], "learning goal")
        students = {s.id for s in self.roster}
        turns = self.transcript.turns
        for i, turn in enumerate(turns):
            if turn.endMs <= turn.startMs or (i > 0 and turn.startMs < turns[i - 1].startMs):
                raise ValueError("Turn timestamps must be ordered and have positive duration")
            sp = turn.speaker
            if sp.kind == "uncertain" and any(c not in students for c in sp.candidateStudentIds):
                raise ValueError("Uncertain attribution candidates must reference the roster")
            if sp.kind == "student" and sp.studentId not in students:
                raise ValueError("Student attribution must reference the session roster")
        for c in self.rubric.criteria:
            if c.noContributionScore is not None and (
                c.kind != "observable-participation"
                or not c.minScore <= c.noContributionScore <= c.maxScore
            ):
                raise ValueError(
                    "No-contribution scoring requires an explicit observable-participation "
                    "rule within range"
                )
            if c.maxScore <= c.minScore:
                raise ValueError(
                    "Each criterion needs a score range with maximum greater than minimum"
                )
        for d in self.documents:
            unique([p.id for p in d.passages], "passage within document")
        return self


MAX_INPUT_BYTES = 2 * 1024 * 1024


def parse_inputs(raw: str) -> AssessmentInputs:
    """Parse an uploaded session JSON file, with the original's size limit."""
    if len(raw.encode()) > MAX_INPUT_BYTES:
        raise ValueError("Input file must be 2 MB or smaller")
    return AssessmentInputs.model_validate_json(raw)


def slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-")[:80] or "x"
