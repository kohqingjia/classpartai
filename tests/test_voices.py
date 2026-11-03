import wave

import numpy as np
import pytest

from classpartai.agents.listener import to_transcript
from classpartai.classlist import ClassList
from classpartai.voices import Voices, check_clip


def clip(path, seconds, amplitude=0.2, rate=16000):
    t = np.arange(int(seconds * rate)) / rate
    samples = (amplitude * np.sin(2 * np.pi * 220 * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(samples.tobytes())
    return path


def test_enrol_checks_length_and_loudness(tmp_path):
    voices = Voices(tmp_path / "enrollments")
    with pytest.raises(ValueError, match="at least 8 s"):
        voices.enrol("alex", "Alex", clip(tmp_path / "short.wav", 3))
    with pytest.raises(ValueError, match="silent"):
        voices.enrol("alex", "Alex", clip(tmp_path / "quiet.wav", 12, amplitude=0.0005))
    voices.enrol("alex", "Alex", clip(tmp_path / "good.wav", 12))
    assert voices.registry() == {"alex": {"name": "Alex", "audio_file": "alex.wav"}}
    assert round(voices.seconds("alex")) == 12
    assert check_clip(voices.clip_path("alex")).ok
    voices.remove("alex")
    assert voices.registry() == {} and not (tmp_path / "enrollments" / "alex.wav").exists()


def test_professor_role_and_turns(tmp_path):
    people = ClassList(tmp_path / "classlist.json")
    people.upsert("Prof Lim", "lim@example.edu", role="professor")
    alex = people.upsert("Alex Tan", "alex@example.edu")
    assert [p.name for p in people.professors()] == ["Prof Lim"]
    assert [s.person_id for s in people.students()] == [alex.person_id]
    result = {
        "segments": [
            {"start": 0, "end": 2, "speaker": "Prof Lim", "text": "Why might an agent help?"},
            {"start": 2, "end": 5, "speaker": "Alex Tan", "text": "It can rewrite the query."},
            {"start": 5, "end": 6, "speaker": "UNKNOWN", "text": "Hmm."},
        ]
    }
    kinds = [
        t.speaker.kind
        for t in to_transcript(result, {"Alex Tan": alex.person_id}, "v1", {"Prof Lim"}).turns
    ]
    assert kinds == ["professor", "student", "uncertain"]


def test_best_match_needs_a_clear_winner():
    from classpartai.agents.listener import best_match

    def m(*pairs):
        return [{"name": n, "score": s} for n, s in pairs]

    assert best_match(m(("Alex", 0.62), ("Priya", 0.21))) == "Alex"
    assert best_match(m(("Alex", 0.48), ("Priya", 0.44))) == "AMBIGUOUS"
    assert best_match(m(("Alex", 0.20), ("Priya", 0.05))) == "UNKNOWN"
    assert best_match([]) == "UNKNOWN"
