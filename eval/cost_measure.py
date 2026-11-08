"""Record what one real assessment run cost, for the Evaluation page's cost comparison.

Run where the app's database is (the VPS container), on a run recorded with the usage ledger:

    python eval/cost_measure.py <run id>  > eval/results/cost-measured.json

It sums the run's model calls from the ledger (tokens and estimated cost, by agent) and counts
the student turns it assessed. The Listener's speed is read from the Listener eval instead.
"""

import json
import sys

from classpartai.config import DATA_DIR
from classpartai.costing import problems, summarise_run
from classpartai.participation.records import Records


def main(run_id: str) -> None:
    result = summarise_run(Records(DATA_DIR / "assessments.db"), run_id)
    for reason in problems(result["run"]):
        print(f"warning: not a fair basis for a lesson's cost: {reason}", file=sys.stderr)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
