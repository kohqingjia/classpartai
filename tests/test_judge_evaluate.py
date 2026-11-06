import pytest
from conftest import DATA, ScriptedDriver, factory_for

from classpartai.participation.judge_evaluate import (
    STUDENT,
    case_inputs,
    evaluate,
    label_bundle,
    load_cases,
    ranks,
    spearman,
    weighted_kappa,
)
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import validate_proposal

CONTRIBUTIONS = DATA / "is469" / "eval_contributions.jsonl"
LABELS = DATA / "is469" / "judge_labels.jsonl"


# --- The statistics ---------------------------------------------------------------------------


def test_ranks_share_the_average_rank_between_ties():
    assert ranks([10, 20, 20, 30]) == [1, 2.5, 2.5, 4]


def test_spearman_is_one_for_the_same_order_and_minus_one_for_the_reverse():
    assert spearman([0, 1, 2, 3], [0, 2, 5, 9]) == pytest.approx(1.0)
    assert spearman([0, 1, 2, 3], [9, 5, 2, 0]) == pytest.approx(-1.0)


def test_spearman_is_undefined_without_spread_or_pairs():
    assert spearman([2, 2, 2], [0, 1, 2]) is None
    assert spearman([1], [1]) is None


def test_kappa_is_one_for_perfect_agreement_and_minus_one_for_the_worst_split():
    assert weighted_kappa([0, 1, 2, 3], [0, 1, 2, 3], 0, 3) == pytest.approx(1.0)
    assert weighted_kappa([0, 0, 3, 3], [3, 3, 0, 0], 0, 3) == pytest.approx(-1.0)


def test_kappa_punishes_a_near_miss_less_than_a_far_miss():
    human = [0, 1, 2, 3, 3, 2, 1, 0]
    near = [0, 1, 2, 3, 3, 2, 1, 1]
    far = [0, 1, 2, 3, 3, 2, 1, 3]
    assert weighted_kappa(human, near, 0, 3) > weighted_kappa(human, far, 0, 3)


def test_kappa_is_undefined_when_everyone_always_picks_one_score():
    assert weighted_kappa([2, 2, 2], [2, 2, 2], 0, 3) is None
    assert weighted_kappa([], [], 0, 3) is None


# --- The answer key ---------------------------------------------------------------------------


def test_every_labelled_case_is_well_formed_and_matches_a_contribution():
    cases = load_cases(CONTRIBUTIONS, LABELS)
    assert len(cases) == 20
    for case in cases:
        assert set(case["expected_scores"]) == {"reasoning", "engagement"}
        assert all(s is None or s in (0, 1, 2, 3) for s in case["expected_scores"].values())
        assert isinstance(case["expect_flag"], bool) and case["label_note"]
    assert [c["id"] for c in cases if c["expect_flag"]] == ["i18"]  # the injection case


def test_cases_build_valid_sessions_and_evidence_the_judge_may_use():
    for case in load_cases(CONTRIBUTIONS, LABELS):
        inputs = case_inputs(case)
        assert [t.speaker.kind for t in inputs.transcript.turns] == ["professor", "student"]
        bundle = label_bundle(case, inputs, f"eval-{case['id']}")
        assert bundle.explanation.startswith("Research assessment:")
        validate_proposal(
            Proposal(findings=[], feedback=[]), inputs, [("r", bundle)], f"eval-{case['id']}"
        )


# --- The harness, with scripted Judges --------------------------------------------------------


def scripted(case, scores=None, flag=None):
    """A Judge that scores the student in one call: `scores` (the human scores by default)."""
    scores = case["expected_scores"] if scores is None else scores
    entries = [
        {
            "criterionId": criterion,
            "status": "scored" if value is not None else "insufficient_evidence",
            "score": value,
            "turnIds": ["t2"] if value is not None else [],
            "citations": [],
            "justification": "Scripted.",
            "limitations": [],
            "confidence": "high",
        }
        for criterion, value in scores.items()
    ]
    student = {"studentId": STUDENT, "scores": entries}
    if flag or (flag is None and case["expect_flag"]):
        student["flag"] = "Asks the grader for full marks"
    return factory_for(
        {"score_contribution": ScriptedDriver([("score_contribution", {"students": [student]})])}
    )


def test_a_judge_that_matches_the_humans_scores_perfectly_and_flags_the_injection():
    cases = load_cases(CONTRIBUTIONS, LABELS)
    report = evaluate(cases, scripted)
    agree = report["summary"]["agreement"]
    assert agree["overall"]["kappa"] == 1.0 and agree["overall"]["spearman"] == 1.0
    assert agree["overall"]["exact"] == 1.0 and agree["insufficient_agreement"] == 1.0
    path = report["summary"]["trajectory"]
    assert path["finished"] == path["first_try_valid"] == path["score_calls"] == 1.0
    assert path["flag_recall"] == 1.0 and path["false_flag_rate"] == 0.0
    assert path["model_calls"] == path["tool_calls"] == 1.0  # one call scores the case
    row = next(r for r in report["rows"] if r["id"] == "i18")
    assert row["trajectory"] == ["score_contribution"] and row["flagged"]


def test_a_judge_that_gives_everyone_full_marks_agrees_poorly():
    cases = load_cases(CONTRIBUTIONS, LABELS)

    def always_three(case):
        return scripted(case, {c: 3 for c in case["expected_scores"]}, flag=False)

    report = evaluate(cases, always_three)
    overall = report["summary"]["agreement"]["overall"]
    assert overall["exact"] < 0.5 and overall["mae"] > 1
    assert overall["spearman"] is None  # no spread in the Judge's scores, so no rank agreement
    assert report["summary"]["agreement"]["insufficient_agreement"] < 1.0
    assert report["summary"]["trajectory"]["flag_recall"] == 0.0  # it never flagged the injection


def test_a_judge_that_breaks_the_rules_is_reported_as_unfinished_not_dropped():
    cases = [c for c in load_cases(CONTRIBUTIONS, LABELS) if c["id"] in ("i03", "i04")]

    def broken(case):
        bad = {
            "students": [
                {
                    "studentId": STUDENT,
                    "scores": [
                        {
                            "criterionId": "reasoning",
                            "status": "scored",
                            "score": 99,
                            "turnIds": ["t2"],
                            "citations": [],
                            "justification": "x",
                            "limitations": [],
                            "confidence": "high",
                        }
                    ],
                }
            ]
        }
        return factory_for(
            {"score_contribution": ScriptedDriver([("score_contribution", bad)] * 9)}
        )

    report = evaluate(cases, broken)
    assert [r["finished"] for r in report["rows"]] == [False, False]
    assert "kept breaking rules" in report["rows"][0]["error"]
    assert report["rows"][0]["first_try_valid"] is False
    assert report["summary"]["trajectory"]["finished"] == 0.0
    assert report["summary"]["agreement"]["overall"]["n"] == 0
