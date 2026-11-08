"""Run the real Listener models on the demo seminars once and cache everything they output, so
eval/listener/compare.py can score configurations offline (no models, no server).

Runs inside the app container, where the models are cached and HF_TOKEN is set:

    docker cp eval/listener/collect.py classpartai-app:/tmp/listener-eval/collect.py
    docker exec classpartai-app python /tmp/listener-eval/collect.py \
        --demos /data/app/demo-seminars --out /tmp/listener-eval/out [--whisper-variants]

It never writes to the app's folders: audio-service's code is copied to a scratch folder (its
per-speaker clips land there instead of the app's shared speaker_clips/), with the enrolments
and the voice model linked in read-only use. For each demo it records:

- ``pipeline``: audio-service ``process_audio`` (Whisper base, pyannote, SpeechBrain per
  diarised speaker with Tina's rule), plus the raw diarisation turns and stage timings;
- ``segment_matches``: every Whisper segment's own clip scored against every enrolled voice
  (what the no-diarisation fallback does);
- ``line_matches``: the same for each script line's true time span (an oracle segmentation,
  to separate voice-embedding quality from segmentation errors);
- ``whisper``: with ``--whisper-variants``, transcripts and runtimes from other model sizes and
  beam widths;
- ``whisper_words``: with ``--add-words`` (a second, quick pass over the records already
  collected), Whisper base beam 5 with word timestamps, to test aligning words rather than
  whole Whisper segments to the diarised speakers;
- ``word_segment_matches``: with ``--add-word-matches`` (third pass; put this checkout's
  ``src`` first on PYTHONPATH), each word-aligned segment's own clip scored against every
  enrolled voice, for the per-segment veto;
- ``turn_matches``: with ``--add-turn-matches`` (fourth pass, same PYTHONPATH), each whole
  turn of several word-aligned segments (``turn_runs``) scored the same way, for the turn
  check.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import wave
from pathlib import Path

SCRATCH = Path("/tmp/listener-eval")
APP_AUDIO = Path("/app/audio-service")
VARIANTS = [("tiny", 5), ("base", 1), ("base", 5), ("small", 5)]


def stage_audio_service() -> Path:
    """A copy of audio-service whose writes stay in the scratch folder."""
    target = SCRATCH / "audio-service"
    target.mkdir(parents=True, exist_ok=True)
    for path in APP_AUDIO.glob("*.py"):
        shutil.copy(path, target / path.name)
    for name in ("enrollments", "models"):
        link = target / name
        if not link.exists():
            link.symlink_to(APP_AUDIO / name)
    return target


def cut(audio_path: str, start: float, end: float, out: Path) -> Path:
    with wave.open(audio_path, "rb") as audio:
        rate = audio.getframerate()
        audio.setpos(int(start * rate))
        frames = audio.readframes(int((end - start) * rate))
        with wave.open(str(out), "wb") as clip:
            clip.setparams(audio.getparams())
            clip.writeframes(frames)
    return out


def cached_identify(speaker_identification):
    """``identify_speaker`` with each enrolled voice embedded once rather than per call.

    ``verify_files`` embeds both files and returns their cosine similarity (same speaker when
    above 0.25), so this gives the same numbers; ``main`` checks that on the first span."""

    model = speaker_identification.speaker_model
    enrolled = []
    for person_id, person in speaker_identification.load_registry().items():
        path = speaker_identification.ENROLLMENT_DIR / person["audio_file"]
        wav = model.load_audio(str(path)).unsqueeze(0)
        enrolled.append((person_id, person["name"], model.encode_batch(wav, normalize=False)))

    def identify(test_file: str) -> list[dict]:
        emb = model.encode_batch(model.load_audio(test_file).unsqueeze(0), normalize=False)
        results = []
        for person_id, name, ref in enrolled:
            score = float(model.similarity(ref, emb)[0].item())
            results.append(
                {"person_id": person_id, "name": name, "score": score, "same_speaker": score > 0.25}
            )
        return sorted(results, key=lambda r: r["score"], reverse=True)

    return identify


def score_spans(audio_path: str, spans: list[tuple[float, float]], tmp: Path, identify) -> list:
    """Every enrolled voice's score for each span (None when too short to embed)."""
    results = []
    for n, (start, end) in enumerate(spans):
        if end - start < 0.5:
            results.append(None)
            continue
        clip = cut(audio_path, start, end, tmp / f"span-{n}.wav")
        results.append(identify(str(clip)))
    return results


def run_pipeline(audio_path: str, pipeline) -> dict:
    captured, timings = {}, {}
    diarize, transcribe = pipeline.diarize_audio, pipeline.run_transcription

    def timed_diarize(path):
        t0 = time.perf_counter()
        captured["turns"] = diarize(path)
        timings["diarization_s"] = time.perf_counter() - t0
        return captured["turns"]

    def timed_transcribe(path):
        t0 = time.perf_counter()
        out = transcribe(path)
        timings["transcription_s"] = time.perf_counter() - t0
        return out

    pipeline.diarize_audio, pipeline.run_transcription = timed_diarize, timed_transcribe
    t0 = time.perf_counter()
    try:
        result = pipeline.process_audio(audio_path)
    finally:
        pipeline.diarize_audio, pipeline.run_transcription = diarize, transcribe
    timings["total_s"] = time.perf_counter() - t0
    return {**result, "diarization_turns": captured.get("turns", []), "timings": timings}


def whisper_variants(audio_path: str) -> list[dict]:
    from faster_whisper import WhisperModel

    runs = []
    for size, beam in VARIANTS:
        root = None if size == "base" else str(SCRATCH / "whisper-models")
        model = WhisperModel(size, device="cpu", compute_type="int8", download_root=root)
        t0 = time.perf_counter()
        segments, _ = model.transcribe(audio_path, beam_size=beam, language="en")
        segments = [{"start": s.start, "end": s.end, "text": s.text.strip()} for s in segments]
        runs.append(
            {"model": size, "beam": beam, "seconds": time.perf_counter() - t0, "segments": segments}
        )
        print(f"  whisper {size} beam {beam}: {runs[-1]['seconds']:.1f}s", flush=True)
    return runs


def whisper_words(audio_path: str) -> dict:
    """Whisper base, beam 5 (the pipeline's settings) with word timestamps."""
    from faster_whisper import WhisperModel

    model = WhisperModel("base", device="cpu", compute_type="int8")
    t0 = time.perf_counter()
    segments, _ = model.transcribe(audio_path, beam_size=5, language="en", word_timestamps=True)
    segments = [
        {
            "start": s.start,
            "end": s.end,
            "text": s.text.strip(),
            "words": [{"start": w.start, "end": w.end, "word": w.word} for w in s.words],
        }
        for s in segments
    ]
    return {"seconds": time.perf_counter() - t0, "segments": segments}


def add_words(out: Path, demos: Path) -> None:
    """``--add-words``: add a word-timestamped transcript to records already collected."""
    for path in sorted(out.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["whisper_words"] = whisper_words(str(demos / f"{record['id']}.wav"))
        print(f"{record['id']}: words in {record['whisper_words']['seconds']:.1f}s", flush=True)
        path.write_text(json.dumps(record, indent=1, default=str))


def add_word_matches(out: Path, demos: Path) -> None:
    """``--add-word-matches``: score each word-aligned segment's own clip (for the veto).
    Needs this checkout's ``src`` first on PYTHONPATH, for ``align_words``."""
    import speaker_identification

    from classpartai.agents.listener import align_words

    identify = cached_identify(speaker_identification)
    tmp = SCRATCH / "clips"
    tmp.mkdir(parents=True, exist_ok=True)
    for path in sorted(out.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        segments = align_words(
            record["whisper_words"]["segments"], record["pipeline"]["diarization_turns"]
        )
        t0 = time.perf_counter()
        spans = [(s["start"], s["end"]) for s in segments]
        record["word_segments"] = spans
        record["word_segment_matches"] = score_spans(
            str(demos / f"{record['id']}.wav"), spans, tmp, identify
        )
        record["word_segment_scoring_s"] = time.perf_counter() - t0
        print(f"{record['id']}: {len(spans)} word segments scored", flush=True)
        path.write_text(json.dumps(record, indent=1, default=str))


def add_turn_matches(out: Path, demos: Path) -> None:
    """``--add-turn-matches``: score each turn of several word-aligned segments as a whole.
    Needs this checkout's ``src`` first on PYTHONPATH, for ``align_words`` and ``turn_runs``."""
    import speaker_identification

    from classpartai.agents.listener import MIN_SEGMENT_SECONDS, align_words, turn_runs

    identify = cached_identify(speaker_identification)
    tmp = SCRATCH / "clips"
    tmp.mkdir(parents=True, exist_ok=True)
    for path in sorted(out.glob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        segments = align_words(
            record["whisper_words"]["segments"], record["pipeline"]["diarization_turns"]
        )
        spans = [
            (segments[run[0]]["start"], segments[run[-1]]["end"])
            for run in turn_runs(segments)
            if len(run) > 1
        ]
        spans = [(a, b) for a, b in spans if b - a >= MIN_SEGMENT_SECONDS]
        record["turn_spans"] = spans
        record["turn_matches"] = score_spans(
            str(demos / f"{record['id']}.wav"), spans, tmp, identify
        )
        print(f"{record['id']}: {len(spans)} turns scored", flush=True)
        path.write_text(json.dumps(record, indent=1, default=str))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demos", default="/data/app/demo-seminars")
    parser.add_argument("--out", default=str(SCRATCH / "out"))
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--whisper-variants", action="store_true")
    parser.add_argument("--add-words", action="store_true", help="only add word timestamps")
    parser.add_argument("--add-word-matches", action="store_true")
    parser.add_argument("--add-turn-matches", action="store_true")
    args = parser.parse_args()
    if args.add_words:
        return add_words(Path(args.out), Path(args.demos))

    sys.path.insert(0, str(stage_audio_service()))
    if args.add_word_matches:
        return add_word_matches(Path(args.out), Path(args.demos))
    if args.add_turn_matches:
        return add_turn_matches(Path(args.out), Path(args.demos))
    import pipeline
    import speaker_identification
    from speaker_identification import identify_speaker, load_registry

    identify = cached_identify(speaker_identification)
    checked = False

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tmp = SCRATCH / "clips"
    tmp.mkdir(parents=True, exist_ok=True)
    for script_path in sorted(Path(args.demos).glob("*.json")):
        wav = script_path.with_suffix(".wav")
        if script_path.name == "voices.json" or not wav.exists():
            continue
        if args.only and script_path.stem not in args.only:
            continue
        print(f"{script_path.stem}", flush=True)
        script = json.loads(script_path.read_text(encoding="utf-8"))
        with wave.open(str(wav), "rb") as audio:
            seconds = audio.getnframes() / audio.getframerate()
        record = {
            "id": script_path.stem,
            "audio_seconds": seconds,
            "script": {k: script[k] for k in ("id", "title", "case", "lines")},
            "registry": {k: v["name"] for k, v in load_registry().items()},
            "pipeline": run_pipeline(str(wav), pipeline),
        }
        whisper = record["pipeline"]["whisper_segments"]
        t0 = time.perf_counter()
        if not checked:  # the cached scorer must agree with SpeechBrain's verify_files
            span = next(s for s in whisper if s["end"] - s["start"] >= 1.0)
            clip = cut(str(wav), span["start"], span["end"], tmp / "check.wav")
            ours, theirs = identify(str(clip)), identify_speaker(str(clip))
            for a, b in zip(ours, theirs, strict=True):
                assert a["name"] == b["name"] and abs(a["score"] - b["score"]) < 1e-4, (a, b)
            checked = True
        record["segment_matches"] = score_spans(
            str(wav), [(s["start"], s["end"]) for s in whisper], tmp, identify
        )
        record["segment_scoring_s"] = time.perf_counter() - t0
        record["line_matches"] = score_spans(
            str(wav), [(ln["start"], ln["end"]) for ln in script["lines"]], tmp, identify
        )
        if args.whisper_variants:
            record["whisper"] = whisper_variants(str(wav))
        timings = record["pipeline"]["timings"]
        print(f"  pipeline {timings['total_s']:.1f}s for {seconds:.0f}s of audio", flush=True)
        (out / f"{script_path.stem}.json").write_text(json.dumps(record, indent=1, default=str))


if __name__ == "__main__":
    main()
