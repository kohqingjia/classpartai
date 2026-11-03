"""Read-only voice enrolment metadata shared by the Listener and its inspector."""

import json
from pathlib import Path

from classpartai.config import ENROLLMENT_DIR


def enrolments(directory: Path = ENROLLMENT_DIR) -> dict:
    registry = directory / "registry.json"
    return json.loads(registry.read_text()) if registry.exists() else {}


def match_rows(diagnostics: dict) -> list[dict]:
    """Keep line attribution and the original verifier decision; never re-identify a voice."""
    rows = []
    for segment in diagnostics.get("aligned_segments", []):
        identity = segment.get("voice_match") or diagnostics.get("voice_matches", {}).get(
            segment.get("speaker"), {}
        )
        matches = sorted(identity.get("matches", []), key=lambda m: m["score"], reverse=True)
        best = matches[0] if matches else None
        second = matches[1] if len(matches) > 1 else None
        rows.append(
            {
                "Start (s)": segment["start"],
                "End (s)": segment["end"],
                "Line": segment.get("text", ""),
                "Identity": identity.get("name", "Not recorded"),
                "Decision": identity.get("status", "Not recorded"),
                "Best voice": best["name"] if best else None,
                "Best cosine": best["score"] if best else None,
                "Runner-up": second["name"] if second else None,
                "Runner-up cosine": second["score"] if second else None,
                "Margin": best["score"] - second["score"] if second else None,
            }
        )
    return rows
