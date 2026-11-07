"""Scoring the Listener against scripted recordings (used by eval/listener/compare.py).

A demo seminar is a recording plus its timed script. Two things are scored:

- Word error rate (WER) of the transcript against the script, after normalising both
  (lower case, no punctuation, hyphens as spaces).
- Speaker attribution per script line. Each transcribed segment is assigned to the script line
  it overlaps most in time, then the line is one of:
    - ``correct``: at least half of its transcribed time carries the right person;
    - ``wrong``: some of it is credited to another student or professor. For a student this is
      the dangerous error: someone gets credit (or blame) for words they never said;
    - ``unattributed``: otherwise (unknown / ambiguous, or nothing transcribed).
  A guest (not enrolled) line is right only when it stays unattributed. Professor lines count
  as right when they go to any professor voice.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

UNATTRIBUTED = "unattributed"


def normalise(text: str) -> list[str]:
    text = text.lower().replace("-", " ").replace("’", "'")
    return re.sub(r"[^a-z0-9' ]+", " ", text).split()


def word_errors(reference: list[str], hypothesis: list[str]) -> int:
    """Levenshtein distance in words (substitutions + deletions + insertions)."""
    previous = list(range(len(hypothesis) + 1))
    for i, ref_word in enumerate(reference, start=1):
        current = [i]
        for j, hyp_word in enumerate(hypothesis, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ref_word != hyp_word))
            )
        previous = current
    return previous[-1]


def wer(reference: str, hypothesis: str) -> tuple[int, int]:
    """(word errors, reference words)."""
    ref = normalise(reference)
    return word_errors(ref, normalise(hypothesis)), len(ref)


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


class People:
    """Who a name is: a student, a professor, or nobody the app would credit."""

    def __init__(self, students: Iterable[str], professors: Iterable[str]):
        self.students = {s.casefold() for s in students}
        self.professors = {p.casefold() for p in professors}

    def role(self, name: str) -> str:
        key = name.casefold()
        if key in self.students:
            return "student"
        if key in self.professors:
            return "professor"
        return UNATTRIBUTED

    def true_role(self, script_speaker: str) -> str:
        """A script line's speaker: their role, or ``guest`` if not enrolled."""
        role = self.role(script_speaker)
        if role == UNATTRIBUTED:
            return "professor" if script_speaker.casefold().startswith("prof") else "guest"
        return role


def line_outcomes(lines: list[dict], segments: list[dict], people: People) -> list[dict]:
    """One outcome per script line. ``segments``: transcribed {start, end, speaker}, where
    ``speaker`` is the name the configuration decided (or UNKNOWN / AMBIGUOUS)."""
    assigned: list[list[dict]] = [[] for _ in lines]
    for seg in segments:
        spans = [overlap(seg["start"], seg["end"], ln["start"], ln["end"]) for ln in lines]
        if spans and max(spans) > 0:
            assigned[spans.index(max(spans))].append(seg)
    outcomes = []
    for line, segs in zip(lines, assigned, strict=True):
        truth = people.true_role(line["speaker"])
        right_time = total_time = 0.0
        wrong_names = set()
        for seg in segs:
            length = seg["end"] - seg["start"]
            total_time += length
            role = people.role(seg["speaker"])
            if role == UNATTRIBUTED:
                continue
            same = (
                role == "professor"
                if truth == "professor"
                else (seg["speaker"].casefold() == line["speaker"].casefold())
            )
            if same:
                right_time += length
            else:
                wrong_names.add(seg["speaker"])
        if wrong_names:
            outcome = "wrong"
        elif truth != "guest" and total_time and right_time >= total_time / 2:
            outcome = "correct"
        elif truth == "guest":
            outcome = "correct"  # a guest left unattributed is the right answer
        else:
            outcome = UNATTRIBUTED
        outcomes.append(
            {
                "speaker": line["speaker"],
                "role": truth,
                "outcome": outcome,
                "credited": sorted(wrong_names),
                # Another student credited with this line: the error that must never go up.
                "wrong_student": any(people.role(n) == "student" for n in wrong_names),
            }
        )
    return outcomes


def tally(outcomes: Iterable[dict]) -> dict:
    """Counts by role: correct / wrong / unattributed, and ``wrong_person``: lines (anyone's)
    credited to a student who did not say them, the number that must never go up."""
    counts = {
        role: {"lines": 0, "correct": 0, "wrong": 0, UNATTRIBUTED: 0}
        for role in ("student", "professor", "guest")
    }
    wrong_person = 0
    for o in outcomes:
        counts[o["role"]]["lines"] += 1
        counts[o["role"]][o["outcome"]] += 1
        wrong_person += o["wrong_student"]
    return {**counts, "wrong_person": wrong_person}


def time_attribution(lines: list[dict], segments: list[dict], people: People) -> dict:
    """Seconds of scripted speech by what the transcript credits them to. Unlike
    ``line_outcomes`` this also counts the few words at a segment's edge that belong to the
    next speaker, which is how a Whisper segment spanning a turn change mis-credits words."""
    seconds = {"right": 0.0, "wrong_student": 0.0, "wrong_other": 0.0, UNATTRIBUTED: 0.0}
    for line in lines:
        truth = people.true_role(line["speaker"])
        for seg in segments:
            shared = overlap(seg["start"], seg["end"], line["start"], line["end"])
            if not shared:
                continue
            role = people.role(seg["speaker"])
            if truth == "professor" and role == "professor":
                seconds["right"] += shared
            elif role == UNATTRIBUTED:
                seconds["right" if truth == "guest" else UNATTRIBUTED] += shared
            elif seg["speaker"].casefold() == line["speaker"].casefold():
                seconds["right"] += shared
            else:
                seconds["wrong_student" if role == "student" else "wrong_other"] += shared
    return seconds
