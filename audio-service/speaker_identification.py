import json
import os
from pathlib import Path

from dotenv import load_dotenv
from speechbrain.inference.speaker import SpeakerRecognition

BASE_DIR = Path(__file__).resolve().parent
ROOT_DIR = BASE_DIR.parent

ENROLLMENT_DIR = BASE_DIR / "enrollments"
REGISTRY_PATH = ENROLLMENT_DIR / "registry.json"

# Load environment variables from project root .env
load_dotenv(ROOT_DIR / ".env")

HF_TOKEN = os.getenv("HF_TOKEN")

if not HF_TOKEN:
    raise RuntimeError("HF_TOKEN environment variable is not set.")


speaker_model = SpeakerRecognition.from_hparams(
    source="speechbrain/spkrec-ecapa-voxceleb",
    savedir=str(BASE_DIR / "models" / "spkrec-ecapa-voxceleb"),
)


def load_registry():
    with open(REGISTRY_PATH) as file:
        return json.load(file)


def compare_speakers(enrollment_file, test_file):
    score, prediction = speaker_model.verify_files(
        str(enrollment_file),
        str(test_file),
    )

    return {
        "score": float(score.item()),
        "same_speaker": bool(prediction.item()),
    }


def identify_speaker(test_file):
    """
    Compare one unknown speaker clip against every registered person.
    Return all comparison results.
    """

    registry = load_registry()
    results = []

    for person_id, person in registry.items():
        enrollment_file = ENROLLMENT_DIR / person["audio_file"]

        comparison = compare_speakers(
            enrollment_file,
            test_file,
        )

        results.append(
            {
                "person_id": person_id,
                "name": person["name"],
                "score": comparison["score"],
                "same_speaker": comparison["same_speaker"],
            }
        )

    # Highest similarity first
    results.sort(
        key=lambda result: result["score"],
        reverse=True,
    )

    return results


def resolve_speaker_identity(test_file):
    """
    Decide the final identity of a diarized speaker.

    Rules:
    - 0 accepted matches -> UNKNOWN
    - 1 accepted match -> registered person's name
    - >1 accepted matches -> AMBIGUOUS
    """

    results = identify_speaker(test_file)

    accepted_matches = [result for result in results if result["same_speaker"]]

    if len(accepted_matches) == 0:
        return {
            "name": "UNKNOWN",
            "status": "unknown",
            "matches": results,
        }

    if len(accepted_matches) > 1:
        return {
            "name": "AMBIGUOUS",
            "status": "ambiguous",
            "matches": results,
        }

    best_match = accepted_matches[0]

    return {
        "name": best_match["name"],
        "status": "identified",
        "score": best_match["score"],
        "matches": results,
    }
