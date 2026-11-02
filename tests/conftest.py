import json
from pathlib import Path

import pytest

from classpartai.assessment import AssessmentInputs
from classpartai.models import ModelCall, ModelTurn
from classpartai.participation.records import Records

DATA = Path(__file__).resolve().parents[1] / "data"


class ScriptedDriver:
    """A fake model that replays tool calls: each step is (tool name, arguments dict)."""

    def __init__(self, steps):
        self.steps = list(steps)
        self.histories = []

    def estimate_tokens(self, history):
        return 10

    def next(self, history):
        self.histories.append(list(history))
        name, args = self.steps.pop(0)
        raw = args if isinstance(args, str) else json.dumps(args)
        return ModelTurn([ModelCall(name, f"call-{len(self.histories)}", raw)], 10)


def factory_for(scripts: dict[str, ScriptedDriver]):
    """Route each agent/role to its script by the first tool it is offered."""

    def factory(instructions, tools):
        names = {t.name for t in tools}
        for key, driver in scripts.items():
            if key in names:
                return driver
        raise AssertionError(f"No script for tools {names}")

    return factory


@pytest.fixture
def inputs() -> AssessmentInputs:
    return AssessmentInputs.model_validate_json((DATA / "sample_assessment.json").read_text())


@pytest.fixture
def fictional() -> AssessmentInputs:
    return AssessmentInputs.model_validate_json((DATA / "fixture-fictional.json").read_text())


@pytest.fixture
def records(tmp_path) -> Records:
    return Records(tmp_path / "test.db")


@pytest.fixture
def session_id(records, inputs) -> str:
    return records.create_session(inputs)


def finding(student, criterion, score, turns, status="scored"):
    return {
        "studentId": student,
        "criterionId": criterion,
        "status": status,
        "score": score,
        "turnIds": turns,
        "citations": [],
        "justification": "Explained with reference to the turn.",
        "limitations": [],
    }


def feedback(student, strengths="Clear explanation of the mechanism.", turns=()):
    return {
        "studentId": student,
        "strengths": strengths,
        "nextStep": "Link your point to one course reading next time.",
        "limitations": [],
        "turnIds": list(turns),
        "citations": [],
        "goalIds": [],
    }


SILENT = "No observed contribution in this session; join in with one question next time."


def full_proposal() -> dict:
    """A complete, valid proposal for the sample session."""
    findings = []
    for student, turns, score in [
        ("alex-tan", ["turn-002", "turn-005"], 3),
        ("priya-nair", ["turn-003"], 1),
        ("jordan-wong", ["turn-006"], 2),
    ]:
        findings += [finding(student, c, score, turns) for c in ("reasoning", "engagement")]
    findings += [
        finding("marcus-lee", c, None, [], "insufficient_evidence")
        for c in ("reasoning", "engagement")
    ]
    return {
        "findings": findings,
        "feedback": [
            feedback("alex-tan", turns=["turn-002"]),
            feedback("priya-nair", "A relevant question that opened a useful contrast."),
            feedback("jordan-wong", "An accurate point about Self-RAG."),
            feedback("marcus-lee", SILENT),
        ],
    }
