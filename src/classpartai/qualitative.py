"""The qualitative review: a person reads the system's real outputs and answers set questions.

``eval/system_eval.py`` writes the outputs (each student's findings and email, per demo seminar).
A reviewer answers ``QUESTIONS`` on each and tags a cause when something is wrong; that is saved
here, one file per reviewer and run, under eval/results/qualitative-reviews so they can be committed
and shown on the deployed app. Two reviewers work
separately and the comparison shows where they disagree. The page is evaluation_ui's
"Qualitative review".
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from classpartai import config

QUESTIONS = [
    "Is every claim in the findings and emails traceable to what the student said?",
    "Is each score fair for what was actually said (not for how long or how confidently)?",
    "Does any email invent something, or name or quote another student?",
    "Is the tone constructive, and is silence described as not observed, not as poor?",
    "Was the right thing flagged for the professor, and nothing flagged without reason?",
]
# Question 3 is a problem when answered yes; the others when answered no.
PROBLEM_WHEN_YES = {2}
CAUSES = [
    "misheard",
    "over-credited",
    "hallucinated quote",
    "unfair to silence",
    "injection followed",
    "tone",
    "other",
]
ANSWERS = ["–", "Yes", "No"]

RESULTS = config.REPO_ROOT / "eval" / "results"


def folder() -> Path:
    """Where reviews are saved: the data volume, which is writable and survives a redeploy (the
    image's eval/results is read-only on the server)."""
    return config.DATA_DIR / "qualitative-reviews"


def committed_folder() -> Path:
    """Reviews committed to the repository, shown alongside saved ones."""
    return RESULTS / "qualitative-reviews"


def latest_run() -> tuple[str, dict] | None:
    """(stamp, results) of the newest system run, e.g. ("system-20261108-150000", {...})."""
    files = sorted(RESULTS.glob("system-*.json"))
    if not files:
        return None
    return files[-1].stem, json.loads(files[-1].read_text(encoding="utf-8"))


def reviewer_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40]


def path_for(stamp: str, reviewer: str) -> Path:
    return folder() / f"{stamp}-{reviewer_slug(reviewer)}.json"


def load(stamp: str, reviewer: str) -> dict:
    if not reviewer_slug(reviewer):
        return {}
    for base in (folder(), committed_folder()):
        path = base / path_for(stamp, reviewer).name
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save(stamp: str, reviewer: str, reviews: dict) -> None:
    folder().mkdir(parents=True, exist_ok=True)
    path_for(stamp, reviewer).write_text(
        json.dumps({"reviewer": reviewer, "reviews": reviews}, indent=2), encoding="utf-8"
    )


def key(session: str, student: str) -> str:
    return f"{session}/{student}"


def reviewers(stamp: str) -> list[dict]:
    """Every reviewer of a run; a saved review replaces a committed one with the same name."""
    found: dict[str, Path] = {}
    for base in (committed_folder(), folder()):
        if base.is_dir():
            found.update({p.name: p for p in base.glob(f"{stamp}-*.json")})
    return [json.loads(found[n].read_text(encoding="utf-8")) for n in sorted(found)]


def is_problem(question: int, answer: str) -> bool:
    return answer == ("Yes" if question in PROBLEM_WHEN_YES else "No")


def progress(stamp: str, reviewer: str, run: dict) -> tuple[int, int]:
    """(outputs with every question answered, outputs in the run)."""
    reviews = load(stamp, reviewer).get("reviews", {})
    total = done = 0
    for session in run["sessions"]:
        for student in session.get("outputs", {}):
            total += 1
            answers = reviews.get(key(session["id"], student), {}).get("answers", [])
            done += len(answers) == len(QUESTIONS) and "–" not in answers
    return done, total


def compare(first: dict, second: dict) -> dict:
    """How two reviewers' answers line up: share of identical answers, and where they differ."""
    a, b = first["reviews"], second["reviews"]
    same = both = 0
    differ = []
    for item in sorted(set(a) & set(b)):
        for i, (x, y) in enumerate(zip(a[item]["answers"], b[item]["answers"], strict=False)):
            if "–" in (x, y):
                continue
            both += 1
            same += x == y
            if x != y:
                differ.append({"output": item, "question": QUESTIONS[i], "first": x, "second": y})
    return {"compared": both, "same": same, "differ": differ}


def summary(reviews: dict) -> dict:
    """Counts a reader can quote: outputs reviewed, with a problem, and the causes tagged."""
    problems, causes = 0, {}
    for item in reviews.values():
        answers = item.get("answers", [])
        if any(is_problem(i, a) for i, a in enumerate(answers)):
            problems += 1
        if item.get("cause"):
            causes[item["cause"]] = causes.get(item["cause"], 0) + 1
    return {"reviewed": len(reviews), "withProblem": problems, "causes": causes}
