"""What ClassPart AI costs per lesson and per semester, against paying a teaching assistant.

Measured, not guessed, where we can: the model cost comes from one real assessment run's usage
ledger, and the Listener's speed from the Listener eval; both are in
eval/results/cost-measured.json, written by eval/cost_measure.py. The rest are assumptions
the Evaluation page lets you change: how many times students speak in a lesson, the server's
monthly price, the exchange rate and the TA's pay.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from classpartai.config import REPO_ROOT

RESULTS = REPO_ROOT / "eval" / "results"
MEASURED = RESULTS / "cost-measured.json"


@dataclass(frozen=True)
class Assumptions:
    lessons: int = 12
    lesson_hours: float = 3.0
    students: int = 40
    contributions: int = 20  # times students speak in one lesson (not everyone does)
    server_usd_month: float = 25.0  # an estimate for a 4-vCPU cloud server
    semester_months: float = 4.0
    sgd_per_usd: float = 1.30
    ta_sgd_semester: float = 590.0
    review_minutes_per_contribution: float = 1.0  # the professor still reads every draft


def measured(path: Path = MEASURED) -> dict | None:
    return json.loads(path.read_text()) if path.exists() else None


def estimate(m: dict, a: Assumptions) -> dict:
    """Per lesson and per semester, in SGD, from ``measured()``."""
    run, listener = m["run"], m["listener"]
    speed = listener["pipeline_seconds"] / listener["audio_seconds"]
    per_contribution = run["usd"] / run["contributions"]
    model_lesson = per_contribution * a.contributions * a.sgd_per_usd
    server_semester = a.server_usd_month * a.semester_months * a.sgd_per_usd
    seconds_per_contribution = run["seconds"] / run["contributions"]
    software = model_lesson * a.lessons + server_semester
    return {
        "model_per_lesson": model_lesson,
        "model_semester": model_lesson * a.lessons,
        "server_semester": server_semester,
        "software_semester": software,
        "software_per_lesson": software / a.lessons,
        "ta_semester": a.ta_sgd_semester,
        "ta_per_lesson": a.ta_sgd_semester / a.lessons,
        "ta_per_class_hour": a.ta_sgd_semester / (a.lessons * a.lesson_hours),
        "saving_semester": a.ta_sgd_semester - software,
        "listener_hours_per_lesson": speed * a.lesson_hours,
        "assessment_minutes_per_lesson": seconds_per_contribution * a.contributions / 60,
        "review_minutes_per_lesson": a.review_minutes_per_contribution * a.contributions,
        # The most a lesson's model calls could cost before the software stops being cheaper.
        "break_even_model_per_lesson": (a.ta_sgd_semester - server_semester) / a.lessons,
    }
