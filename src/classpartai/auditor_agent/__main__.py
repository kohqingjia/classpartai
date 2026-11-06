"""JSON CLI using explicit provider settings; credentials are never printed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .agent import AuditorAgent
from .contracts import ContractError
from .examples.demo import FictionalModelDouble, MemoryEvidenceReader
from .tools import Evidence


def load_json(path: str) -> dict | list:
    if path == "-":
        raw = sys.stdin.read(150001)
    else:
        with Path(path).open() as stream:
            raw = stream.read(150001)
    if len(raw.encode()) > 150000:
        raise ContractError("JSON input exceeds 150 KB")
    return json.loads(raw, object_pairs_hook=no_duplicate_keys)


def no_duplicate_keys(pairs: list[tuple]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ContractError("Duplicate JSON object key")
        result[key] = value
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Standalone Auditor: reads trusted JSON context; never approves, grades or sends"
        )
    )
    parser.add_argument("request", help="JSON request path or - for stdin")
    parser.add_argument(
        "--evidence",
        required=True,
        help="Caller-authorised local JSON evidence list (demo adapter)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--test-double",
        action="store_true",
        help="Explicit fictional protocol fixture; NOT live LLM behaviour",
    )
    mode.add_argument(
        "--local-model", help="Explicitly configured installed no-cost local tool-calling model"
    )
    parser.add_argument(
        "--provider",
        choices=("openai", "groq", "local"),
        help="Override AUDITOR_PROVIDER from .env",
    )
    parser.add_argument("--model", help="Override the selected provider model for this run")
    parser.add_argument("--local-url", help="Override AUDITOR_MODEL_URL from environment/.env")
    args = parser.parse_args()
    try:
        request = load_json(args.request)
        records = load_json(args.evidence)
        if not isinstance(records, list) or len(records) > 100:
            raise ContractError("Evidence file must be a bounded list")
        reader = MemoryEvidenceReader([Evidence.parse(r) for r in records])
        if args.model and args.local_model:
            raise ContractError("Choose --model or --local-model, not both")
        agent = AuditorAgent(
            reader,
            model=FictionalModelDouble() if args.test_double else None,
            model_name=args.local_model if args.local_model else args.model,
            base_url=args.local_url,
            local=bool(args.local_model),
            provider=args.provider,
        )
        result = agent.run(request)
        output = result.to_dict()
        output["execution_label"] = (
            "fictional_test_double"
            if args.test_double
            else getattr(agent.model, "provider", "local_model")
            if agent.model
            else "configuration_blocked"
        )
        print(json.dumps(output, indent=2, allow_nan=False))
        return 0
    except (ContractError, ValueError, OSError):
        print(
            json.dumps(
                {
                    "error": "invalid_input_or_configuration",
                    "message": (
                        "Invalid contract, inaccessible JSON file or "
                        "disallowed local configuration; no audit pass "
                        "issued"
                    ),
                }
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
