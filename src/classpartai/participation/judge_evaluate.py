"""Judge agent trajectory/output evaluation, on cases a person has already scored.

Each case is one professor question and one student answer (data/is469/eval_contributions.jsonl)
joined by id to the human scores for each rubric criterion (data/is469/judge_labels.jsonl). A
score of ``null`` means "insufficient evidence": the Judge should not give a number.

Research is held fixed: the Judge is given an evidence bundle written from the labels (what a
perfect Research agent would report), so differences come from the Judge, not from retrieval.

Output metrics, over the criteria where both the human and the Judge gave a number:

    spearman        rank correlation between human and Judge scores
    kappa           quadratic-weighted Cohen's kappa (agreement beyond chance, near misses
                    count for more than far misses)
    exact, within_one, mae   share equal, share within one point, mean absolute error
    insufficient_agreement   share of criteria where both or neither said "insufficient evidence"

Trajectory metrics, per case:

    finished        the Judge handed over findings that passed validation
    first_try_valid no score it proposed was refused by the rules
    read_first      it read the student's turns before scoring
    flag_recall     it flagged the cases a person said need the professor (e.g. an injection)
    false_flag_rate it flagged cases nobody expected to be flagged
    model_calls, tool_calls, tokens, seconds   what it cost
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

from classpartai import config
from classpartai.assessment import AssessmentInputs
from classpartai.evidence import EvidenceBundle
from classpartai.models import (
    WORKFLOW_LIMITS,
    BudgetExceeded,
    SharedBudget,
    WorkflowProgress,
)
from classpartai.participation.judge import FLAG_PREFIX, ROLE, judge
from classpartai.participation.roles import DriverFactory
from classpartai.participation.validation import Unprocessable

STUDENT = "student"


def load_jsonl(path: str | Path) -> list[dict]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def load_cases(contributions: str | Path, labels: str | Path) -> list[dict]:
    """Every labelled contribution joined to its human scores. Unlabelled items are skipped."""
    scores = {row["id"]: row for row in load_jsonl(labels)}
    cases = []
    for item in load_jsonl(contributions):
        if item["id"] in scores:
            label = scores[item["id"]]
            cases.append(
                {
                    **item,
                    "expected_scores": label["scores"],
                    "expect_flag": label.get("expect_flag"),
                    "reviewed": label.get("reviewed", False),
                    "label_note": label.get("note", ""),
                }
            )
    return cases


def case_inputs(case: dict) -> AssessmentInputs:
    """A one-student, two-turn session: the professor's question, then the student's answer."""
    rubric = json.loads((config.REPO_ROOT / "data" / "default_rubric.json").read_text("utf-8"))
    return AssessmentInputs.model_validate(
        {
            "formatVersion": 1,
            "provenance": "fictional-development",
            "courseTitle": "IS469",
            "sessionTitle": f"Judge evaluation {case['id']}",
            "roster": [{"id": STUDENT, "displayName": "Student"}],
            "transcript": {
                "version": "eval-1",
                "reviewStatus": "reviewed",
                "turns": [
                    {
                        "id": "t1",
                        "startMs": 0,
                        "endMs": 5000,
                        "speaker": {"kind": "professor", "label": "Professor"},
                        "text": case["question"],
                    },
                    {
                        "id": "t2",
                        "startMs": 5000,
                        "endMs": 15000,
                        "speaker": {"kind": "student", "studentId": STUDENT},
                        "text": case["text"],
                    },
                ],
            },
            "rubric": rubric,
            "documents": [
                {
                    "id": "placeholder",
                    "version": "1",
                    "title": "Placeholder",
                    "source": "evaluation",
                    "authorisedForCourse": True,
                    "passages": [{"id": "p1", "page": 1, "text": "Not used by the Judge."}],
                }
            ],
        }
    )


def label_bundle(case: dict, inputs: AssessmentInputs, session_id: str) -> EvidenceBundle:
    """What a perfect Research agent would hand the Judge, written from the labels."""
    facts = []
    if case.get("expected_correctness"):
        facts.append(f"the answer is {case['expected_correctness'].replace('_', ' ')}")
    elif case.get("expected_sources") == ["web"]:
        facts.append("the claim was checked on the web and holds")
    else:
        facts.append("there is no factual claim to check")
    if case.get("expected_answers_question"):
        facts.append(f"does it answer the question: {case['expected_answers_question']}")
    if case.get("expected_reasoning"):
        facts.append(f"the student's reasoning: {case['expected_reasoning']}")
    if case.get("expected_mistake"):
        facts.append(f"kind of mistake: {case['expected_mistake'].replace('_', ' ')}")
    return EvidenceBundle(
        sessionId=session_id,
        question=case["question"],
        transcriptVersion=inputs.transcript.version,
        rubric={"id": inputs.rubric.id, "version": inputs.rubric.version},
        status="sufficient",
        explanation="Research assessment: " + "; ".join(facts) + ".",
        turnIds=["t2"],
        citations=[],
        conflicts=[],
        gaps=[],
    )


def run_case(case: dict, factory: DriverFactory, evidence_mode: str = "labels") -> dict:
    """Run the Judge on one case and score it against the human scores."""
    inputs = case_inputs(case)
    session_id = f"eval-{case['id']}"
    evidence = (
        [(f"research-{case['id']}", label_bundle(case, inputs, session_id))]
        if evidence_mode == "labels"
        else []
    )
    progress = WorkflowProgress()
    started = time.monotonic()
    budget = SharedBudget(progress, started + WORKFLOW_LIMITS["seconds"])
    error = None
    proposal = None
    try:
        proposal = judge(inputs, evidence, budget, factory, session_id)
    except (Unprocessable, BudgetExceeded, RuntimeError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    return score(case, proposal, progress, error, time.monotonic() - started)


def score(
    case: dict,
    proposal,
    progress: WorkflowProgress,
    error: str | None = None,
    seconds: float = 0.0,
) -> dict:
    turns = [t for t in progress.roleCalls if t["role"] == ROLE]
    tools = [(t.get("calls") or [{}])[0].get("name") for t in turns]
    refused_scores = sum(
        1
        for t, name in zip(turns, tools, strict=True)
        if name == "score_contribution" and t["outcome"] == "refused"
    )
    findings = {f.criterionId: f for f in proposal.findings} if proposal else {}
    first_score = tools.index("score_contribution") if "score_contribution" in tools else None
    expected = case["expected_scores"]
    return {
        "id": case["id"],
        "finished": proposal is not None,
        "error": error,
        "expected": expected,
        "predicted": {
            c: (findings[c].score if c in findings and findings[c].status == "scored" else None)
            for c in expected
        }
        if proposal
        else None,
        "confidence": {c: f.confidence for c, f in findings.items()},
        "flagged": any(FLAG_PREFIX in n for f in findings.values() for n in f.limitations),
        "expect_flag": case.get("expect_flag"),
        "trajectory": tools,
        "refused_calls": sum(t["outcome"] == "refused" for t in turns),
        "first_try_valid": refused_scores == 0,
        "read_first": first_score is not None and "get_contributions" in tools[:first_score],
        "model_calls": progress.modelCalls,
        "tool_calls": progress.toolCalls,
        "tokens": progress.tokens,
        "seconds": round(seconds, 3),
    }


# --- Agreement statistics (no dependencies, so they are easy to check by hand) ---------------


def ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1  # ties share their average rank
        i = j + 1
    return out


def spearman(a: list[float], b: list[float]) -> float | None:
    """Rank correlation; None when it is undefined (fewer than two pairs, or no spread)."""
    if len(a) < 2 or len(a) != len(b):
        return None
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb, strict=True))
    va = sum((x - ma) ** 2 for x in ra)
    vb = sum((y - mb) ** 2 for y in rb)
    return None if va == 0 or vb == 0 else cov / (va * vb) ** 0.5


def weighted_kappa(a: list[int], b: list[int], low: int, high: int) -> float | None:
    """Quadratic-weighted Cohen's kappa over the integer scale low..high."""
    n, k = len(a), high - low + 1
    if n == 0 or k < 2 or len(a) != len(b):
        return None
    observed = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b, strict=True):
        observed[x - low][y - low] += 1
    row = [sum(r) for r in observed]
    col = [sum(observed[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            weight = ((i - j) / (k - 1)) ** 2
            num += weight * observed[i][j]
            den += weight * row[i] * col[j] / n
    return None if den == 0 else 1 - num / den


def agreement(pairs: list[tuple[float, float]], low: int, high: int) -> dict:
    human = [h for h, _ in pairs]
    model = [m for _, m in pairs]
    n = len(pairs)
    return {
        "n": n,
        "spearman": spearman(human, model),
        "kappa": weighted_kappa([round(h) for h in human], [round(m) for m in model], low, high),
        "exact": sum(h == m for h, m in pairs) / n if n else None,
        "within_one": sum(abs(h - m) <= 1 for h, m in pairs) / n if n else None,
        "mae": sum(abs(h - m) for h, m in pairs) / n if n else None,
    }


def summarise(rows: list[dict], inputs: AssessmentInputs | None = None) -> dict:
    inputs = inputs or case_inputs({"id": "scale", "question": "q", "text": "a"})
    ranges = {c.id: (c.minScore, c.maxScore) for c in inputs.rubric.criteria}
    done = [r for r in rows if r["finished"]]
    pairs: dict[str, list[tuple[float, float]]] = {c: [] for c in ranges}
    cells = agree_insufficient = 0
    for row in done:
        for criterion, human in row["expected"].items():
            model = row["predicted"][criterion]
            cells += 1
            agree_insufficient += (human is None) == (model is None)
            if human is not None and model is not None:
                pairs[criterion].append((human, model))
    low = min(lo for lo, _ in ranges.values())
    high = max(hi for _, hi in ranges.values())
    expected_flag = [r for r in done if r["expect_flag"] is True]
    unexpected = [r for r in done if r["expect_flag"] is False]

    def mean(key: str, source: list[dict] = rows) -> float | None:
        values = [float(r[key]) for r in source]
        return round(sum(values) / len(values), 3) if values else None

    def rounded(stats: dict) -> dict:
        return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in stats.items()}

    return {
        "agreement": {
            "overall": rounded(agreement([p for ps in pairs.values() for p in ps], low, high)),
            "per_criterion": {c: rounded(agreement(p, *ranges[c])) for c, p in pairs.items()},
            "insufficient_agreement": round(agree_insufficient / cells, 3) if cells else None,
        },
        "trajectory": {
            "finished": mean("finished"),
            "first_try_valid": mean("first_try_valid", done),
            "read_first": mean("read_first", done),
            "flag_recall": mean("flagged", expected_flag),
            "false_flag_rate": mean("flagged", unexpected),
            "refused_calls": mean("refused_calls"),
            "model_calls": mean("model_calls"),
            "tool_calls": mean("tool_calls"),
            "tokens": mean("tokens"),
            "seconds": mean("seconds"),
        },
    }


def evaluate(
    cases: list[dict],
    factory_for_case: Callable[[dict], DriverFactory],
    evidence_mode: str = "labels",
) -> dict:
    rows = [run_case(case, factory_for_case(case), evidence_mode) for case in cases]
    return {"summary": summarise(rows), "rows": rows}


def format_table(report: dict) -> str:
    summary = report["summary"]
    agree, path = summary["agreement"], summary["trajectory"]

    def cell(value) -> str:
        return "n/a" if value is None else f"{value:.2f}"

    lines = [
        "| output agreement with human scores | n | spearman | kappa | exact | within 1 | mae |"
    ]
    lines.append("|---|---|---|---|---|---|---|")
    groups = {"all criteria": agree["overall"], **agree["per_criterion"]}
    for name, s in groups.items():
        lines.append(
            f"| {name} | {s['n']} | {cell(s['spearman'])} | {cell(s['kappa'])} | "
            f"{cell(s['exact'])} | {cell(s['within_one'])} | {cell(s['mae'])} |"
        )
    lines.append(f"\ninsufficient-evidence agreement: {cell(agree['insufficient_agreement'])}")
    lines += ["", "| trajectory | per case |", "|---|---|"]
    lines += [f"| {key} | {cell(value)} |" for key, value in path.items()]
    return "\n".join(lines)
