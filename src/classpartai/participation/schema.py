"""Shapes for findings, feedback, audits and drafts (ported from participation/schema.ts)."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CitationRef(Strict):
    evidenceRunId: str = Field(min_length=1, max_length=80)
    passageId: str = Field(min_length=1, max_length=300)


class Finding(Strict):
    studentId: str = Field(min_length=1, max_length=80)
    criterionId: str = Field(min_length=1, max_length=80)
    status: Literal["scored", "insufficient_evidence"]
    score: float | None
    turnIds: list[str] = Field(max_length=30)
    citations: list[CitationRef] = Field(max_length=12)
    justification: str = Field(min_length=1, max_length=1500)
    limitations: list[str] = Field(max_length=10)


class Feedback(Strict):
    studentId: str = Field(min_length=1, max_length=80)
    strengths: str = Field(min_length=1, max_length=1500)
    nextStep: str = Field(min_length=1, max_length=1500)
    limitations: list[str] = Field(max_length=10)
    turnIds: list[str] = Field(max_length=30)
    citations: list[CitationRef] = Field(max_length=12)
    goalIds: list[str] = Field(max_length=10)


class Proposal(Strict):
    findings: list[Finding] = Field(max_length=15000)
    feedback: list[Feedback] = Field(max_length=500)


class ModelAuditIssue(Strict):
    id: str = Field(min_length=1, max_length=80)
    studentId: str | None
    criterionId: str | None
    detail: str = Field(min_length=1, max_length=1000)
    kind: Literal["support", "attribution", "contradiction", "feedback", "uncertainty"]


class ModelAudit(Strict):
    issues: list[ModelAuditIssue] = Field(max_length=100)
    resolvedIssueIds: list[str] = Field(max_length=100)
    resolutionReason: str = Field(min_length=1, max_length=1000)
    notes: str = Field(min_length=1, max_length=1500)


class AuditIssue(BaseModel):
    id: str
    studentId: str | None
    criterionId: str | None
    kind: str
    detail: str
    severity: Literal["blocking", "review"]
    disposition: Literal["open", "revised"]
    resolution: str | None


class Audit(BaseModel):
    modelReviewed: bool
    notes: str
    issues: list[AuditIssue]


class DraftContent(Proposal):
    model_config = ConfigDict(extra="forbid")
    audit: Audit
    revisionNote: str
