"""Record what one real assessment run cost, for the Evaluation page's cost comparison.

Run where the app's database is (the VPS container), on a run recorded with the usage ledger:

    python eval/cost_measure.py <run id>  > eval/results/cost-measured.json

It sums the run's model calls from the ledger (tokens and estimated cost, by agent) and counts
the student turns it assessed. The Listener's speed is read from the Listener eval instead.
"""

import json
import sys
from collections import defaultdict

from classpartai import usage
from classpartai.config import DATA_DIR
from classpartai.participation.records import Records


def main(run_id: str) -> None:
    records = Records(DATA_DIR / "assessments.db")
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
    print(
        json.dumps(
            {
                "run": {
                    "id": run["id"],
                    "session": inputs.sessionTitle,
                    "status": run["status"],
                    "stopReason": run["stop_reason"],
                    "model": json.loads(run["manifest"]).get("model"),
                    "recordedAt": run["created_at"],
                    "audio_seconds": round(turns[-1].endMs / 1000) if turns else 0,
                    "contributions": sum(t.speaker.kind == "student" for t in turns),
                    "students": len(inputs.roster),
                    "seconds": progress.get("elapsedSeconds"),
                    "modelCalls": progress.get("modelCalls"),
                    "usd": round(sum(a["usd"] for a in by_agent.values()), 5),
                    "byAgent": {
                        k: {n: round(v, 5) for n, v in a.items()} for k, a in by_agent.items()
                    },
                },
                "prices": {
                    "usdPerMillionTokens": usage.price_for(
                        json.loads(run["manifest"]).get("model")
                    ),
                    "source": "data/model_prices.json",
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main(sys.argv[1])
