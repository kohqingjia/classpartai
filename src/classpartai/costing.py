"""What ClassPart AI costs per lesson and per semester, against paying a teaching assistant.

Measured, not guessed, where we can: the model cost comes from one real assessment run's usage
ledger (eval/results/cost-measured.json, written by eval/cost_measure.py), and the Listener's
speed from the Listener eval (eval/results/listener-20261107.json). The rest are assumptions
the Evaluation page lets you change: how many times students speak in a lesson, the server's
monthly price, the exchange rate and the TA's pay.
"""

import json
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from classpartai.config import REPO_ROOT

RESULTS = REPO_ROOT / "eval" / "results"
MEASURED = RESULTS / "cost-measured.json"
LISTENER = RESULTS / "listener-20261107.json"
# The seven demo recordings in the Listener eval: 498 s of audio (listener-20261107.md).
LISTENER_AUDIO_SECONDS = 498.0


@dataclass(frozen=True)
class Assumptions:
    lessons: int = 12
    lesson_hours: float = 3.0
    students: int = 40
    contributions: int = 20  # times students speak in one lesson (not everyone does)
    server_sgd_month: float = 32.0  # an estimate for a 4-vCPU cloud server
    semester_months: float = 4.0
    sgd_per_usd: float = 1.30  # OpenAI bills in US$; everything shown is S$
    ta_sgd_semester: float = 590.0
    review_minutes_per_contribution: float = 1.0  # the professor still reads every draft


# The agents a complete assessment uses. A run missing one did not do the whole job, so its cost
# is not the cost of an assessment.
AGENTS = ("coordinator", "research", "judge", "auditor", "feedback")
FINISHED = ("ready_for_professor_review",)


def summarise_run(records, run_id: str) -> dict:
    """One run's model calls from the usage ledger (tokens and estimated cost, by agent), in the
    shape of eval/results/cost-measured.json. ``run_id`` may be a prefix."""
    run = records._one("SELECT * FROM participation_runs WHERE id LIKE ?", (run_id + "%",))
    progress = json.loads(run["progress"])
    inputs = records.inputs(run["session_id"])
    turns = inputs.transcript.turns
    by_agent: dict = defaultdict(lambda: defaultdict(float))
    for e in records.events(run_id=run["id"]):
        if e["kind"] not in ("model", "embedding"):
            continue
        a = by_agent[e["agent"]]
        a["calls"] += 1
        for k in ("input_tokens", "cached_tokens", "output_tokens", "reasoning_tokens"):
            a[k] += e[k] or 0
        a["usd"] += e["cost_usd"] or 0
    from classpartai import usage

    model = json.loads(run["manifest"]).get("model")
    return {
        "run": {
            "id": run["id"],
            "session": inputs.sessionTitle,
            "status": run["status"],
            "stopReason": run["stop_reason"],
            "model": model,
            "recordedAt": run["created_at"],
            "audio_seconds": round(turns[-1].endMs / 1000) if turns else 0,
            "contributions": sum(t.speaker.kind == "student" for t in turns),
            "students": len(inputs.roster),
            "seconds": progress.get("elapsedSeconds"),
            "modelCalls": progress.get("modelCalls"),
            "usd": round(sum(a["usd"] for a in by_agent.values()), 5),
            "byAgent": {k: {n: round(v, 5) for n, v in a.items()} for k, a in by_agent.items()},
        },
        "prices": {
            "usdPerMillionTokens": usage.price_for(model),
            "source": "data/model_prices.json",
        },
    }


def problems(run: dict) -> list[str]:
    """Why a measured run is not a fair basis for a lesson's cost (empty if it is)."""
    out = []
    if run.get("stopReason") not in FINISHED:
        out.append(
            f"it stopped because of “{(run.get('stopReason') or 'unknown').replace('_', ' ')}”, "
            "not because the drafts were ready"
        )
    missing = [a for a in AGENTS if a not in run.get("byAgent", {})]
    if missing:
        out.append("no model calls from " + ", ".join(missing))
    if not run.get("contributions") or not run.get("students"):
        out.append("it has no student contributions to divide by")
    return out


def latest_complete(records) -> dict | None:
    """The newest run in the app's own ledger that finished and used every agent, in the shape
    ``estimate`` takes. Costs then follow the code as it is, not one old run."""
    for row in records.runs_with_usage(None, limit=50):
        if row["stop_reason"] not in FINISHED or not row["calls"]:
            continue
        found = summarise_run(records, row["id"])
        if not problems(found["run"]):
            return found
    return None


def measured(path: Path = MEASURED, listener: Path = LISTENER, records=None) -> dict | None:
    """A measured run, plus the Listener's measured speed. With ``records``, the newest complete
    run from the app's ledger wins; otherwise the committed run in eval/results."""
    if not listener.exists():
        return None
    from_ledger = latest_complete(records) if records is not None else None
    found = from_ledger or (json.loads(path.read_text(encoding="utf-8")) if path.exists() else None)
    if found is None:
        return None
    timings = json.loads(listener.read_text(encoding="utf-8"))["timings"].values()
    return {
        **found,
        "source": "ledger" if from_ledger else "file",
        "listener": {
            "pipeline_seconds": sum(t["total_s"] for t in timings),
            "audio_seconds": LISTENER_AUDIO_SECONDS,
            "cpu": "4-core VPS CPU, nothing else running",
        },
    }


def estimate(m: dict, a: Assumptions) -> dict:
    """Per lesson and per semester, in SGD, from ``measured()``."""
    run, listener = m["run"], m["listener"]
    speed = listener["pipeline_seconds"] / listener["audio_seconds"]
    # Research reads each answer, so it grows with how many answers there are. Everything else
    # (Coordinator, Judge, Auditor, Feedback) works per student or per run, so it grows with the
    # class. Dividing the whole run by contributions undercounted a class where most students
    # speak little.
    by_agent = run.get("byAgent") or {}
    if by_agent:
        research_usd = by_agent.get("research", {}).get("usd", 0.0)
        per_answer = research_usd / run["contributions"]
        per_student = (run["usd"] - research_usd) / run["students"]
        model_usd = per_answer * a.contributions + per_student * a.students
    else:
        model_usd = run["usd"] / run["contributions"] * a.contributions
    model_lesson = model_usd * a.sgd_per_usd
    server_semester = a.server_sgd_month * a.semester_months
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
