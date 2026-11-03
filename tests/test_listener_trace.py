"""The production audio adapter retains diagnostics without altering identity decisions."""

import importlib.util
import sys
from types import SimpleNamespace

from classpartai.agents.listener import to_transcript
from classpartai.config import AUDIO_SERVICE_DIR
from classpartai.voices import match_rows


def test_pipeline_retains_verifier_decision_and_raw_whisper_lines(monkeypatch):
    segments = [{"start": 0, "end": 2, "text": "One line."}]
    aligned = [{**segments[0], "speaker": "SPEAKER_00"}]
    identity = {
        "name": "AMBIGUOUS",
        "status": "ambiguous",
        "matches": [{"name": "A", "score": 0.8}, {"name": "B", "score": 0.7}],
    }
    monkeypatch.setitem(
        sys.modules, "alignment", SimpleNamespace(align_speakers=lambda *_: aligned)
    )
    monkeypatch.setitem(sys.modules, "diarization", SimpleNamespace(diarize_audio=lambda _: []))
    monkeypatch.setitem(
        sys.modules,
        "speaker_extraction",
        SimpleNamespace(extract_speaker_audio=lambda *_: {"SPEAKER_00": "clip.wav"}),
    )
    monkeypatch.setitem(
        sys.modules,
        "speaker_identification",
        SimpleNamespace(resolve_speaker_identity=lambda _: identity),
    )
    monkeypatch.syspath_prepend(str(AUDIO_SERVICE_DIR))
    spec = importlib.util.spec_from_file_location(
        "test_audio_pipeline", AUDIO_SERVICE_DIR / "pipeline.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module, "run_transcription", lambda _: {"language": "en", "segments": segments}
    )
    result = module.process_audio("unused.wav")
    assert result["whisper_segments"] == segments
    assert result["aligned_segments"] == aligned
    assert result["voice_matches"]["SPEAKER_00"] == identity
    assert result["segments"][0]["speaker"] == "AMBIGUOUS"
    # A large diagnostic cosine/margin never silently overrides the existing verifier result.
    assert match_rows(result)[0]["Identity"] == "AMBIGUOUS"
    assert to_transcript(result, {"A": "a", "B": "b"}, "v1").turns[0].speaker.kind == "uncertain"
