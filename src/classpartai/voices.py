"""Voice enrolment: one short clip per person, which the Listener matches speakers against.

Clips and the registry live in ENROLLMENT_DIR (audio-service/enrollments, a Docker volume on the
server), never in git: they are personal data. The registry format is Tina's
(audio-service/speaker_identification.py): {person_id: {"name", "audio_file"}}; the Listener names
a speaker by the registered ``name``, so names must match the class list.

``demo`` entries are the synthetic voices of the demo recording (data/demo_audio); they are kept
apart so the class list and the setup checklist only count real people.
"""

import json
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MIN_SECONDS = 8.0  # shorter clips identify people unreliably
GOOD_SECONDS = 20.0
MIN_RMS = 0.01  # quieter than this is (nearly) silence


@dataclass
class ClipCheck:
    seconds: float
    loud_enough: bool

    @property
    def ok(self) -> bool:
        return self.seconds >= MIN_SECONDS and self.loud_enough

    def problem(self) -> str | None:
        if self.seconds < MIN_SECONDS:
            return f"Only {self.seconds:.0f} s of audio: record at least {MIN_SECONDS:.0f} s"
        if not self.loud_enough:
            return "Almost silent: check the microphone and record again"
        return None


def check_clip(path: Path) -> ClipCheck:
    """Length and loudness of a 16-bit PCM WAV clip."""
    with wave.open(str(path), "rb") as clip:
        frames = clip.readframes(clip.getnframes())
        seconds = clip.getnframes() / clip.getframerate()
        width = clip.getsampwidth()
    if width != 2 or not frames:
        return ClipCheck(seconds, bool(frames))
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768
    return ClipCheck(seconds, float(np.sqrt(np.mean(samples**2))) >= MIN_RMS)


class Voices:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.registry_path = self.dir / "registry.json"

    def registry(self) -> dict:
        if not self.registry_path.exists():
            return {}
        return json.loads(self.registry_path.read_text())

    def _save(self, registry: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(json.dumps(registry, indent=2))

    def ensure(self) -> None:
        """The Listener reads the registry at start-up: make sure it exists."""
        if not self.registry_path.exists():
            self._save({})

    def get(self, person_id: str) -> dict | None:
        return self.registry().get(person_id)

    def clip_path(self, person_id: str) -> Path | None:
        entry = self.get(person_id)
        return self.dir / entry["audio_file"] if entry else None

    def enrol(self, person_id: str, name: str, wav: Path, demo: bool = False) -> ClipCheck:
        """Store a 16 kHz mono WAV as this person's voice sample, if it is usable."""
        check = check_clip(wav)
        if not check.ok:
            raise ValueError(check.problem())
        self.dir.mkdir(parents=True, exist_ok=True)
        target = self.dir / f"{person_id}.wav"
        target.write_bytes(Path(wav).read_bytes())
        registry = self.registry()
        registry[person_id] = {"name": name, "audio_file": target.name}
        if demo:
            registry[person_id]["demo"] = True
        self._save(registry)
        return check

    def remove(self, person_id: str) -> None:
        registry = self.registry()
        entry = registry.pop(person_id, None)
        if entry:
            (self.dir / entry["audio_file"]).unlink(missing_ok=True)
            self._save(registry)

    def seconds(self, person_id: str) -> float | None:
        path = self.clip_path(person_id)
        if path is None or not path.exists():
            return None
        return check_clip(path).seconds
