"""Score Listener configurations on the cached demo-seminar runs (offline: no models).

    uv run python eval/listener/compare.py                     # eval/listener/cache/*.json
    uv run python eval/listener/compare.py --cache DIR --out eval/results

The cache comes from eval/listener/collect.py (run once in the app container). Writes
eval/results/listener-<date>.md (tables and reading) and .json (every line's outcome).

Configurations (each decides a name, UNKNOWN or AMBIGUOUS for every Whisper segment):

- A: diarised speakers, Tina's rule: AMBIGUOUS when more than one enrolled voice passes
  SpeechBrain's same-speaker threshold (0.25). What audio-service decides.
- B: diarised speakers, ``best_match``: best score >= min_score and >= min_margin ahead.
- C: no diarisation: each segment's own clip through ``best_match`` (the fallback; segments
  under 1 s stay UNKNOWN).
- B+veto: B, but a segment whose own clip clearly names a different enrolled voice becomes
  AMBIGUOUS (guards against diarisation merging two people into one speaker).
- W: words aligned to the diarised turns (``align_words``), each speaker through
  ``best_match``; W+veto adds the per-segment veto.
- W+veto+turn: W+veto, plus the same check on each whole turn of several segments
  (``turn_runs``), so a turn cut into segments too short to check is still checked. What the
  app does (``decide_speakers``).
- oracle: each script line's true time span through ``best_match`` (an upper bound on the
  voice match alone; not a real configuration).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from classpartai.agents.listener import (
    MATCH_MIN_MARGIN,
    MATCH_MIN_SCORE,
    MIN_SEGMENT_SECONDS,
    align_words,
    best_match,
    decide_speakers,
    turn_runs,
    veto,
)
from classpartai.config import AUDIO_SERVICE_DIR
from classpartai.listener_eval import People, line_outcomes, tally, time_attribution, wer

sys.path.insert(0, str(AUDIO_SERVICE_DIR))  # Tina's speaker_mapping, for decide_speakers

STUDENTS = ("Koh Qing Jia", "tasmin", "tina", "le yong")
PROFESSORS = ("prof", "Prof Lim (demo)", "Prof Wynter")  # class-list professor + demo voices
SCORES = (0.25, 0.35, 0.45)
MARGINS = (0.05, 0.10, 0.15)


def cluster_identity(record: dict, cluster: str) -> dict:
    return record["pipeline"]["voice_matches"].get(cluster, {"name": "UNKNOWN", "matches": []})


def config_a(record: dict) -> list[dict]:
    return [
        {**s, "speaker": cluster_identity(record, s["speaker"])["name"]}
        for s in record["pipeline"]["aligned_segments"]
    ]


def config_b(record: dict, score: float, margin: float) -> list[dict]:
    return [
        {
            **s,
            "speaker": best_match(cluster_identity(record, s["speaker"])["matches"], score, margin),
        }
        for s in record["pipeline"]["aligned_segments"]
    ]


def segment_name(record: dict, n: int, score: float, margin: float) -> str:
    seg, matches = record["pipeline"]["whisper_segments"][n], record["segment_matches"][n]
    if matches is None or seg["end"] - seg["start"] < MIN_SEGMENT_SECONDS:
        return "UNKNOWN"
    return best_match(matches, score, margin)


def config_c(record: dict, score: float, margin: float) -> list[dict]:
    return [
        {**s, "speaker": segment_name(record, n, score, margin)}
        for n, s in enumerate(record["pipeline"]["whisper_segments"])
    ]


def config_veto(record: dict, score: float, margin: float) -> list[dict]:
    return [
        {**seg, "speaker": veto(seg, matches, score, margin)}
        for seg, matches in zip(
            config_b(record, score, margin), record["segment_matches"], strict=True
        )
    ]


def config_words(record: dict, score: float, margin: float) -> list[dict]:
    segments = align_words(
        record["whisper_words"]["segments"], record["pipeline"]["diarization_turns"]
    )
    return [
        {
            **s,
            "speaker": best_match(cluster_identity(record, s["speaker"])["matches"], score, margin),
        }
        for s in segments
    ]


def config_words_veto(record: dict, score: float, margin: float) -> list[dict]:
    segments = config_words(record, score, margin)
    spans = [tuple(s) for s in record["word_segments"]]
    assert spans == [(s["start"], s["end"]) for s in segments], "re-run --add-word-matches"
    return [
        {**seg, "speaker": veto(seg, matches, score, margin)}
        for seg, matches in zip(segments, record["word_segment_matches"], strict=True)
    ]


def config_words_veto_turn(record: dict, score: float, margin: float) -> list[dict]:
    vetoed = config_words_veto(record, score, margin)
    named = config_words(record, score, margin)
    turns = dict(zip(map(tuple, record["turn_spans"]), record["turn_matches"], strict=True))
    out = [dict(seg) for seg in vetoed]
    for run in turn_runs(
        align_words(record["whisper_words"]["segments"], record["pipeline"]["diarization_turns"])
    ):
        span = (named[run[0]]["start"], named[run[-1]]["end"])
        if len(run) < 2 or span not in turns:
            continue
        for n in run:
            if out[n]["speaker"] == named[n]["speaker"]:
                turn = {**named[n], "start": span[0], "end": span[1]}
                out[n]["speaker"] = veto(turn, turns[span], score, margin)
    return out


def config_shipped(record: dict) -> list[dict]:
    """The app's own ``decide_speakers`` on the cached pipeline output, with each line's voice
    scores looked up in the cache instead of computed (thresholds: the module's constants)."""
    cached = {
        (round(a, 3), round(b, 3)): m
        for (a, b), m in zip(
            record["word_segments"] + record["turn_spans"],
            record["word_segment_matches"] + record["turn_matches"],
            strict=True,
        )
    }
    result = {
        **record["pipeline"],
        "whisper_segments": record["whisper_words"]["segments"],
        "speaker_segments": record["pipeline"]["diarization_turns"],
    }
    decided = decide_speakers(result, lambda a, b: cached[(round(a, 3), round(b, 3))])
    return [{**seg, "speaker": seg["voice_match"]["name"]} for seg in decided["aligned_segments"]]


def config_oracle(record: dict, score: float, margin: float) -> list[dict]:
    lines = record["script"]["lines"]
    return [
        {**ln, "speaker": best_match(m, score, margin) if m else "UNKNOWN"}
        for ln, m in zip(lines, record["line_matches"], strict=True)
    ]


def score_config(records: list[dict], decide, people: People) -> dict:
    per_demo, everything = {}, []
    seconds = {"right": 0.0, "wrong_student": 0.0, "wrong_other": 0.0, "unattributed": 0.0}
    for record in records:
        segments = decide(record)
        outcomes = line_outcomes(record["script"]["lines"], segments, people)
        per_demo[record["id"]] = outcomes
        everything += outcomes
        for key, value in time_attribution(record["script"]["lines"], segments, people).items():
            seconds[key] += value
    return {"totals": {**tally(everything), "seconds": seconds}, "lines": per_demo}


def row(name: str, totals: dict) -> str:
    s, p, g = totals["student"], totals["professor"], totals["guest"]
    return (
        f"| {name} | {totals['wrong_person']} | {s['correct']}/{s['lines']} | {s['wrong']} | "
        f"{s['unattributed']} | {p['correct']}/{p['lines']} | {p['wrong']} | "
        f"{g['correct']}/{g['lines']} | {totals['seconds']['wrong_student']:.1f} s | "
        f"{totals['seconds']['wrong_other']:.1f} s |"
    )


HEADER = (
    "| Configuration | Credited to wrong student | Student lines right | Student wrong | "
    "Student unattributed | Professor right | Professor wrong | Guest left unattributed | "
    "Speech credited to wrong student | Speech wrongly given to a professor |\n"
    "|---|---|---|---|---|---|---|---|---|---|"
)


def whisper_table(records: list[dict]) -> tuple[list[str], dict]:
    runs: dict[tuple[str, int | str], dict] = {}
    for record in records:
        reference = " ".join(ln["text"] for ln in record["script"]["lines"])
        variants = list(record.get("whisper") or [])
        if "whisper_words" in record:  # what the app now runs
            variants.append(
                {"model": "base", "beam": "5 + word timings", **record["whisper_words"]}
            )
        for v in variants:
            errors, words = wer(reference, " ".join(s["text"] for s in v["segments"]))
            entry = runs.setdefault((v["model"], v["beam"]), {"errors": 0, "words": 0, "s": 0.0})
            entry["errors"] += errors
            entry["words"] += words
            entry["s"] += v["seconds"]
            entry.setdefault("demos", {})[record["id"]] = errors / words
    audio = sum(r["audio_seconds"] for r in records)
    lines = [
        "| Whisper | Beam | WER | Transcription time | Real-time factor |",
        "|---|---|---|---|---|",
    ]
    for (model, beam), e in sorted(runs.items(), key=lambda kv: kv[1]["s"]):
        lines.append(
            f"| {model} | {beam} | {e['errors'] / e['words']:.1%} | {e['s']:.0f} s | "
            f"{e['s'] / audio:.2f} |"
        )
    return lines, {f"{m}-beam{b}": e for (m, b), e in runs.items()}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", default="eval/listener/cache")
    parser.add_argument("--out", default="eval/results")
    args = parser.parse_args()
    records = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(Path(args.cache).glob("*.json"))
    ]
    people = People(STUDENTS, PROFESSORS)
    default = (MATCH_MIN_SCORE, MATCH_MIN_MARGIN)

    grid = {}
    configs = [("B", config_b), ("C", config_c), ("B+veto", config_veto)]
    if all("whisper_words" in r for r in records):
        configs.append(("W", config_words))
    if all("word_segment_matches" in r for r in records):
        configs.append(("W+veto", config_words_veto))
    if all("turn_matches" in r for r in records):
        configs.append(("W+veto+turn", config_words_veto_turn))
    names = [name for name, _ in configs]
    for name, fn in configs:
        for s in SCORES:
            for m in MARGINS:
                grid[(name, s, m)] = score_config(
                    records, lambda r, fn=fn, s=s, m=m: fn(r, s, m), people
                )
    results = {"A": score_config(records, config_a, people)}
    oracle = score_config(records, lambda r: config_oracle(r, *default), people)
    shipped = None
    if "W+veto+turn" in names:
        shipped = score_config(records, config_shipped, people)
        assert shipped == grid[("W+veto+turn", *default)], "decide_speakers differs"

    # Per-demo WER of the pipeline's own transcript (Whisper base, beam 5).
    wer_rows, total_err, total_words = [], 0, 0
    for record in records:
        reference = " ".join(ln["text"] for ln in record["script"]["lines"])
        hypothesis = " ".join(s["text"] for s in record["pipeline"]["whisper_segments"])
        errors, words = wer(reference, hypothesis)
        total_err, total_words = total_err + errors, total_words + words
        clusters = len(record["pipeline"]["voice_matches"])
        speakers = len({ln["speaker"] for ln in record["script"]["lines"]})
        t = record["pipeline"]["timings"]
        wer_rows.append(
            f"| {record['id']} | {record['audio_seconds']:.0f} s | {errors / words:.1%} "
            f"({errors}/{words}) | {speakers} | {clusters} | {t['transcription_s']:.0f} s | "
            f"{t['diarization_s']:.0f} s | {t['total_s']:.0f} s |"
        )
    whisper_lines, whisper_json = whisper_table(records)

    md = [
        f"# Listener evaluation ({date.today().isoformat()})",
        "",
        f"{len(records)} scripted demo seminars "
        f"({sum(r['audio_seconds'] for r in records) / 60:.1f} min, "
        f"{sum(len(r['script']['lines']) for r in records)} lines), real models, run once in "
        "the app container (`eval/listener/collect.py`), scored offline from the cache "
        "(`eval/listener/compare.py`). Speaker outcomes are per script line; see "
        "`src/classpartai/listener_eval.py` for the rules.",
        "",
        "## Speaker attribution",
        "",
        HEADER,
        row("A · diarised + Tina's rule (current)", results["A"]["totals"]),
    ]
    for name in names:
        md.append(
            row(f"{name} · {default[0]:.2f} / {default[1]:.2f}", grid[(name, *default)]["totals"])
        )
    if shipped:
        md.append(row("**the app now** (`decide_speakers`, = W+veto+turn)", shipped["totals"]))
    md.append(row("oracle line spans · 0.35 / 0.10", oracle["totals"]))
    md += ["", "### Threshold grid (min score / min margin)", "", HEADER]
    for (name, s, m), res in grid.items():
        md.append(row(f"{name} · {s:.2f} / {m:.2f}", res["totals"]))
    md += [
        "",
        "## Transcription",
        "",
        "Pipeline transcript (Whisper base int8, beam 5) against the script:",
        "",
        "| Demo | Audio | WER | Speakers in script | Diarised speakers | Whisper | pyannote | "
        "Pipeline total |",
        "|---|---|---|---|---|---|---|---|",
        *wer_rows,
        f"| **all** | | **{total_err / total_words:.1%}** ({total_err}/{total_words}) | | | | | |",
        "",
        "Model size and beam width (same CPU, run one after another):",
        "",
        *whisper_lines,
    ]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = out / f"listener-{date.today().strftime('%Y%m%d')}"
    report = stem.with_suffix(".md")
    # The hand-written "## Reading" at the end of an earlier run's report is kept.
    reading = (
        report.read_text(encoding="utf-8").partition("\n## Reading")[2] if report.exists() else ""
    )
    report.write_text("\n".join(md) + "\n" + (f"\n## Reading{reading}" if reading else ""))
    stem.with_suffix(".json").write_text(
        json.dumps(
            {
                "demos": [r["id"] for r in records],
                "A": results["A"],
                # Every line's outcome at the default thresholds; totals only for the grid.
                "default": {n: grid[(n, *default)] for n in names},
                "shipped": shipped,
                "grid": {f"{n} {s:.2f}/{m:.2f}": r["totals"] for (n, s, m), r in grid.items()},
                "oracle": oracle,
                "wer": {"base-beam5-pipeline": total_err / total_words},
                "whisper": whisper_json,
                "timings": {r["id"]: r["pipeline"]["timings"] for r in records},
            },
            indent=1,
        )
    )
    print("\n".join(md))


if __name__ == "__main__":
    main()
