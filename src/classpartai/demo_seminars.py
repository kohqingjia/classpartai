"""Demo seminars: scripted mock classes, one per edge case, for the presentation.

Each demo is a recording plus the script it was made from, with each line's time in the
recording, so the class can check what the Listener heard against what was said. The audio is
cloned from our own enrolled voices, which is personal data, so it lives only on the server
(DATA_DIR/demo-seminars), never in git; tools/demo_seminars/ makes it from scripts.json.

    demo-seminars/
      voices.json        [{"personId", "name", "role", "file"}]: synthetic voices to enrol
      voices/<file>      their samples
      <id>.wav           a demo's recording
      <id>.json          {"id", "title", "case", "lines": [{"speaker", "text", "start", "end"}]}
"""

import json
from pathlib import Path


def available(root: Path) -> list[dict]:
    """The demos whose recording is present, in id order."""
    demos = []
    for path in sorted(root.glob("*.json")):
        if path.name == "voices.json" or not path.with_suffix(".wav").exists():
            continue
        demos.append(
            {**json.loads(path.read_text(encoding="utf-8")), "audio": str(path.with_suffix(".wav"))}
        )
    return demos


def voices(root: Path) -> list[dict]:
    """The synthetic voices the demos need enrolled (e.g. the demo professor)."""
    path = root / "voices.json"
    if not path.exists():
        return []
    return [
        {**v, "path": str(root / "voices" / v["file"])}
        for v in json.loads(path.read_text(encoding="utf-8"))
    ]
