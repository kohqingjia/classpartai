"""The Listener re-decides who said what from the pipeline's output (no models: fakes only)."""

import wave

import pytest

from classpartai.agents.listener import (
    align_words,
    decide_speakers,
    span_scorer,
    to_transcript,
    veto,
)
from classpartai.config import AUDIO_SERVICE_DIR


@pytest.fixture(autouse=True)
def audio_service_path(monkeypatch):
    monkeypatch.syspath_prepend(str(AUDIO_SERVICE_DIR))  # for Tina's speaker_mapping


@pytest.fixture
def wav(tmp_path):
    path = tmp_path / "seminar.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * 16000 * 12)
    return str(path)


def scores(*pairs):
    return [{"name": n, "score": s, "same_speaker": s > 0.25} for n, s in pairs]


def word(start, end, text):
    return {"start": start, "end": end, "word": f" {text}"}


TURNS = [
    {"start": 0.0, "end": 4.0, "speaker": "SPEAKER_00"},
    {"start": 4.3, "end": 10.0, "speaker": "SPEAKER_01"},
]
# One Whisper segment running across the turn change at 4 s, as Whisper often does.
WHISPER = [
    {
        "start": 0.0,
        "end": 10.0,
        "text": "Overlap keeps sentences whole. Keyword search finds exact terms.",
        "words": [
            word(0.0, 1.0, "Overlap"),
            word(1.0, 2.0, "keeps"),
            word(2.0, 3.0, "sentences"),
            word(3.0, 3.9, "whole."),
            word(4.4, 5.5, "Keyword"),
            word(5.5, 7.0, "search"),
            word(7.0, 8.5, "finds"),
            word(8.5, 9.0, "exact"),
            word(9.0, 10.0, "terms."),
        ],
    }
]


def pipeline_result(**changes):
    result = {
        "language": "en",
        "whisper_segments": WHISPER,
        "speaker_segments": TURNS,
        "aligned_segments": [{**WHISPER[0], "speaker": "SPEAKER_01"}],
        "voice_matches": {
            # Tina's rule: both pass 0.25, so AMBIGUOUS, although Tasmin is clearly ahead.
            "SPEAKER_00": {"name": "AMBIGUOUS", "status": "ambiguous", "matches": []},
            "SPEAKER_01": {"name": "AMBIGUOUS", "status": "ambiguous", "matches": []},
        },
    }
    result["voice_matches"]["SPEAKER_00"]["matches"] = scores(("tina", 0.26), ("tasmin", 0.80))
    result["voice_matches"]["SPEAKER_01"]["matches"] = scores(("tina", 0.83), ("tasmin", 0.25))
    return {**result, **changes}


def own_voice(*answers):
    """A fake voice scorer returning one answer per clip, in order."""
    calls = []

    def identify(start, end):
        calls.append((start, end))
        return answers[len(calls) - 1]

    identify.calls = calls
    return identify


def test_clear_speakers_are_named_and_words_split_at_the_turn_change():
    identify = own_voice(
        scores(("tasmin", 0.70), ("tina", 0.20)), scores(("tina", 0.75), ("tasmin", 0.22))
    )
    result = decide_speakers(pipeline_result(), identify)
    assert [(s["speaker"], s["text"]) for s in result["segments"]] == [
        ("tasmin", "Overlap keeps sentences whole."),
        ("tina", "Keyword search finds exact terms."),
    ]
    assert len(identify.calls) == 2  # each line checked on its own voice
    tasmin = result["voice_matches"]["SPEAKER_00"]
    assert tasmin["name"] == "tasmin" and tasmin["matches"][0]["name"] == "tasmin"
    assert tasmin["verifier"] == {"name": "AMBIGUOUS", "status": "ambiguous"}
    line = result["aligned_segments"][0]["voice_match"]
    assert line["status"] == "identified" and line["scores_from"] == "line"
    assert result["pipeline_aligned_segments"][0]["speaker"] == "SPEAKER_01"
    kinds = [
        t.speaker.kind for t in to_transcript(result, {"tasmin": "t1", "tina": "t2"}, "v").turns
    ]
    assert kinds == ["student", "student"]


def test_a_line_whose_own_voice_names_someone_else_is_not_credited():
    # Diarisation merged Tina and Tasmin into SPEAKER_01, named "tina"; the second line's own
    # voice is clearly Tasmin's, so it must not be credited to Tina.
    turns = [{"start": 0.0, "end": 10.0, "speaker": "SPEAKER_01"}]
    segments = [
        {**WHISPER[0], "end": 4.0, "words": WHISPER[0]["words"][:4], "text": "a"},
        {**WHISPER[0], "start": 4.4, "words": WHISPER[0]["words"][4:], "text": "b"},
    ]
    identify = own_voice(
        scores(("tina", 0.70), ("tasmin", 0.20)), scores(("tasmin", 0.62), ("tina", 0.35))
    )
    result = decide_speakers(
        pipeline_result(speaker_segments=turns, whisper_segments=segments), identify
    )
    assert [s["speaker"] for s in result["segments"]] == ["tina", "AMBIGUOUS"]
    vetoed = result["aligned_segments"][1]["voice_match"]
    assert vetoed["status"] == "vetoed" and vetoed["speaker_name"] == "tina"
    turn = to_transcript(result, {"tasmin": "t1", "tina": "t2"}, "v").turns[1]
    assert turn.speaker.kind == "uncertain"


def test_without_word_timings_the_pipeline_alignment_is_used():
    whisper = [{k: v for k, v in WHISPER[0].items() if k != "words"}]
    identify = own_voice(scores(("tina", 0.75), ("tasmin", 0.22)))
    result = decide_speakers(pipeline_result(whisper_segments=whisper), identify)
    assert [s["speaker"] for s in result["segments"]] == ["tina"]


def test_unknown_speakers_and_short_lines_are_not_rechecked():
    result = pipeline_result()
    result["voice_matches"]["SPEAKER_00"]["matches"] = scores(("tina", 0.20), ("tasmin", 0.10))
    identify = own_voice(scores(("tina", 0.75), ("tasmin", 0.22)))
    decided = decide_speakers(result, identify)
    assert [s["speaker"] for s in decided["segments"]] == ["UNKNOWN", "tina"]
    assert len(identify.calls) == 1
    short = {"start": 0.0, "end": 0.6, "speaker": "tina"}
    assert veto(short, scores(("tasmin", 0.9), ("tina", 0.1))) == "tina"


def test_align_words_bridges_small_gaps_only():
    turns = [{"start": 0.0, "end": 1.0, "speaker": "A"}, {"start": 3.0, "end": 4.0, "speaker": "B"}]
    segment = {
        "start": 0.0,
        "end": 4.0,
        "text": "",
        "words": [word(0.2, 0.8, "one"), word(1.2, 1.4, "two"), word(1.9, 2.1, "three")],
    }
    aligned = align_words([segment], turns)
    assert [(s["speaker"], s["text"]) for s in aligned] == [("A", "one two"), ("UNKNOWN", "three")]


def test_span_scorer_cuts_the_stretch_it_scores(wav):
    seconds = []

    def identify(clip):
        with wave.open(clip, "rb") as audio:
            seconds.append(audio.getnframes() / audio.getframerate())
        return []

    with span_scorer(wav, identify) as score_span:
        score_span(1.0, 3.5)
        score_span(10.0, 12.0)
    assert seconds == [2.5, 2.0]
