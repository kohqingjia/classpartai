"""① Listener injection screen: how many attacks it catches, and how many innocent lines it flags.

Compares the first pattern the project shipped (as it was in the Auditor's tool) with the one the
Listener now uses, on the labelled lines in data/is469/injection_cases.jsonl. No model and no
cost, so it can run anywhere:

    uv run python eval/injection_eval.py

Writes eval/results/injection-<date>.json and .md. Labels: ``attack`` should be flagged,
``benign`` should not, ``quoted_example`` is a student discussing an attack and should not be
flagged as one.
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from classpartai.injection import SUSPECTED, injection_signal

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "data" / "is469" / "injection_cases.jsonl"
RESULTS = ROOT / "eval" / "results"

# The first screen, unchanged: the pattern the Auditor's detect_injection tool used.
LEGACY = re.compile(
    "ignore (?:all |previous |the "
    ")*(?:instructions|rubric|rules)|give (?:me|this student) "
    "(?:full|maximum|5/5)|system prompt|you are now (?:the |a "
    ")?grader|override (?:the )?(?:grade|score)",
    re.I,
)


def legacy_flags(text: str) -> bool:
    return bool(LEGACY.search(text))  # it had no benign-quote rule worth counting here


def current_flags(text: str) -> bool:
    return injection_signal(text)["classification"] == SUSPECTED


def score(cases: list[dict], flags) -> dict:
    attacks = [c for c in cases if c["label"] == "attack"]
    others = [c for c in cases if c["label"] != "attack"]
    caught = [c["id"] for c in attacks if flags(c["text"])]
    false_alarms = [c["id"] for c in others if flags(c["text"])]
    flagged = len(caught) + len(false_alarms)
    return {
        "attacks": len(attacks),
        "caught": len(caught),
        "recall": len(caught) / len(attacks),
        "precision": len(caught) / flagged if flagged else None,
        "false_alarms": false_alarms,
        "missed": [c["id"] for c in attacks if c["id"] not in caught],
    }


def main() -> None:
    cases = [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line]
    results = {
        "first pattern": score(cases, legacy_flags),
        "widened pattern": score(cases, current_flags),
    }
    stamp = datetime.now(UTC).strftime("%Y%m%d")
    lines = [
        f"# Injection screen: {len(cases)} labelled lines ({stamp})",
        "",
        "| Screen | Attacks caught | Recall | Precision | False alarms |",
        "|---|---|---|---|---|",
    ]
    for name, r in results.items():
        precision = "n/a" if r["precision"] is None else f"{r['precision']:.2f}"
        lines.append(
            f"| {name} | {r['caught']}/{r['attacks']} | {r['recall']:.2f} | {precision} | "
            f"{', '.join(r['false_alarms']) or 'none'} |"
        )
    lines += [
        "",
        "Missed by the widened pattern: "
        + (", ".join(results["widened pattern"]["missed"]) or "none"),
    ]
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"injection-{stamp}.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    (RESULTS / f"injection-{stamp}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
