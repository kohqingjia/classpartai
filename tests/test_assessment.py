import json

import pytest
from pydantic import ValidationError

from classpartai.assessment import AssessmentInputs


def test_sample_and_fixture_are_valid(inputs, fictional):
    assert len(inputs.roster) == 4 and len(fictional.roster) == 3


def mutate(inputs, fn):
    raw = json.loads(inputs.model_dump_json())
    fn(raw)
    return raw


def test_rejects_duplicate_roster_ids(inputs):
    raw = mutate(inputs, lambda r: r["roster"].append(r["roster"][0]))
    with pytest.raises(ValidationError, match="Duplicate roster"):
        AssessmentInputs.model_validate(raw)


def test_student_turn_must_reference_roster(inputs):
    raw = mutate(inputs, lambda r: r["transcript"]["turns"][1]["speaker"].update(studentId="ghost"))
    with pytest.raises(ValidationError, match="session roster"):
        AssessmentInputs.model_validate(raw)


def test_turns_must_be_ordered(inputs):
    raw = mutate(inputs, lambda r: r["transcript"]["turns"][2].update(startMs=0, endMs=1))
    with pytest.raises(ValidationError, match="ordered"):
        AssessmentInputs.model_validate(raw)


def test_no_contribution_score_needs_observable_rule(inputs):
    raw = mutate(inputs, lambda r: r["rubric"]["criteria"][0].update(noContributionScore=0))
    with pytest.raises(ValidationError, match="observable-participation"):
        AssessmentInputs.model_validate(raw)
