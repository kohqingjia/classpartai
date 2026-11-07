"""Scoring rules of the Listener evaluation (src/classpartai/listener_eval.py)."""

from classpartai.listener_eval import People, line_outcomes, normalise, tally, time_attribution, wer

PEOPLE = People(["Alex", "priya"], ["prof"])
LINES = [
    {"speaker": "Prof Lim (demo)", "start": 0, "end": 5},
    {"speaker": "Alex", "start": 5, "end": 10},
    {"speaker": "Priya", "start": 10, "end": 15},
    {"speaker": "Guest", "start": 15, "end": 20},
]


def seg(start, end, speaker):
    return {"start": start, "end": end, "speaker": speaker}


def test_wer_ignores_case_punctuation_and_hyphens():
    assert normalise("Trade-off, it's FINE.") == ["trade", "off", "it's", "fine"]
    assert wer("the cat sat", "The cat, sat!") == (0, 3)
    assert wer("the cat sat on the mat", "the cat sat on mat today") == (2, 6)


def test_line_outcomes_by_role():
    segments = [
        seg(0, 5, "prof"),  # the professor's line goes to a professor voice
        seg(5, 9, "Alex"),
        seg(9.2, 10, "UNKNOWN"),  # a short unknown tail doesn't undo Alex's line
        seg(10, 15, "AMBIGUOUS"),
        seg(15, 20, "UNKNOWN"),  # the guest stays unattributed: right
    ]
    outcomes = line_outcomes(LINES, segments, PEOPLE)
    assert [o["outcome"] for o in outcomes] == ["correct", "correct", "unattributed", "correct"]
    assert tally(outcomes)["wrong_person"] == 0


def test_any_credit_to_another_student_is_wrong_person():
    segments = [
        seg(0, 5, "Alex"),  # the professor's words credited to a student
        seg(5, 9, "Alex"),
        seg(9, 10, "Priya"),  # a sliver of Alex's line credited to Priya still counts
        seg(10, 15, "prof"),  # a student's line given to the professor: wrong, not dangerous
        seg(15, 20, "Priya"),  # a guest's words credited to a student
    ]
    outcomes = line_outcomes(LINES, segments, PEOPLE)
    assert [o["outcome"] for o in outcomes] == ["wrong"] * 4
    totals = tally(outcomes)
    assert totals["wrong_person"] == 3
    assert totals["student"] == {"lines": 2, "correct": 0, "wrong": 2, "unattributed": 0}


def test_time_attribution_counts_words_across_a_turn_change():
    segments = [
        seg(0, 6, "prof"),  # runs one second into Alex's line
        seg(6, 10, "Alex"),
        seg(10, 15, "Alex"),  # Priya's line credited to Alex
        seg(15, 20, "UNKNOWN"),
    ]
    seconds = time_attribution(LINES, segments, PEOPLE)
    assert seconds == {"right": 14.0, "wrong_student": 5.0, "wrong_other": 1.0, "unattributed": 0.0}


def test_untranscribed_line_is_unattributed():
    outcomes = line_outcomes(LINES[1:2], [], PEOPLE)
    assert outcomes[0]["outcome"] == "unattributed"
