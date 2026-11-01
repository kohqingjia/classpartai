"""The data each agent hands to the next.

These models are the contract between the five stages. Each owner can change how their stage
works, but not the shape of what it returns, without agreeing it with the stages either side:

    Listener -> list[Contribution]
    Research -> Research          (per contribution)
    Judge    -> Judgement         (per contribution)
    Auditor  -> Audit             (per contribution)
    Action   <- SessionResults    (everything above, for one class)
"""

from typing import Literal

from pydantic import BaseModel, Field

SpeakerStatus = Literal["identified", "unknown", "ambiguous"]


class Contribution(BaseModel):
    """One speaking turn by one student (Listener output)."""

    id: str
    session_id: str
    person_id: str | None = Field(
        description="Class-list ID; None if the speaker wasn't identified"
    )
    speaker: str = Field(description="Display name, or UNKNOWN / AMBIGUOUS")
    speaker_status: SpeakerStatus
    start: float
    end: float
    text: str
    substantive: bool = Field(True, description="False for 'can you repeat that' and similar")


class Evidence(BaseModel):
    source: Literal["course", "web"]
    reference: str = Field(description="Slide deck + page, reading, or URL")
    snippet: str


class Research(BaseModel):
    """What the Research agent found to check a contribution against."""

    route: Literal["course", "web", "none"]
    evidence: list[Evidence] = []
    verified: bool = Field(False, description="True if the evidence supports grading the claim")


class CriterionScore(BaseModel):
    criterion: str
    score: int = Field(ge=1, le=5)
    rationale: str


class Judgement(BaseModel):
    """The Judge agent's rubric scores for a contribution."""

    scores: list[CriterionScore]
    overall: float = Field(ge=1, le=5)
    rationale: str
    confidence: float = Field(ge=0, le=1)


class Audit(BaseModel):
    """The Auditor agent's verdict on a Judgement."""

    verdict: Literal["approved", "rejudged", "escalated"]
    issues: list[str] = []


class ScoredContribution(BaseModel):
    contribution: Contribution
    research: Research
    judgement: Judgement | None = Field(
        None, description="None when not scored (speaker unidentified or not substantive)"
    )
    audit: Audit | None = None


class SessionResults(BaseModel):
    """Everything about one class session; the Action agent's input."""

    session_id: str
    course: str
    date: str
    topic: str = ""
    items: list[ScoredContribution]
    placeholder_stages: list[str] = Field(
        [], description="Stages that ran as placeholders, so outputs can be labelled as such"
    )
