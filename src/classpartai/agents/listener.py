"""① Listener: turn a recording into a reviewed-transcript draft (owner: Tina, CPA-18/19/20).

Wraps audio-service/pipeline.py and maps its output onto the assessment transcript format.
Identified speakers become student turns; UNKNOWN / AMBIGUOUS become "uncertain" turns, which
can never establish a student's score. The professor confirms the transcript before it is used.

Every student or uncertain turn is also screened for words aimed at the grader
(``screen_injection``); the flag rides on the turn (``Turn.injection``).

The pipeline's diarised speakers are then re-decided here (``decide_speakers``): words go to
the speaker turn they fall in, each speaker is named with ``best_match``, and a line whose own
voice clearly names someone else stays uncertain. eval/results/listener-20261107.md measured
why (Tina's verifier rule left clear speakers ambiguous; whole Whisper segments ran across
turn changes; diarisation once merged two students).

If Tina's pipeline can't load (its pyannote diarization model is gated on Hugging Face, so a
token whose account hasn't accepted the model's terms gets a 403), the fallback skips
diarization: Whisper's segments are matched one by one against the enrolled voices with the
same SpeechBrain check. Short or unmatched segments stay uncertain.
"""

import itertools
import json
import subprocess
import sys
import tempfile
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from classpartai.assessment import AssessmentInputs, Transcript
from classpartai.config import AUDIO_SERVICE_DIR
from classpartai.injection import NONE, injection_signal

MIN_SEGMENT_SECONDS = 1.0  # shorter clips are too little voice to identify anyone
# Naming a voice, per diarised speaker and per sentence. Tina's rule ("more than one enrolled
# voice passes the verifier's 0.25 -> ambiguous") left clear speakers ambiguous (0.80 vs 0.26),
# so the best match must be good and clearly ahead of the runner-up instead.
MATCH_MIN_SCORE = 0.35
MATCH_MIN_MARGIN = 0.10
WORD_GAP_SECONDS = 0.5  # a word in a gap between turns joins a turn at most this far away

Identify = Callable[[str], list[dict]]  # a clip's path -> every enrolled voice's score, best first
ScoreSpan = Callable[[float, float], list[dict]]  # (start s, end s) -> the same, for that stretch


def best_match(
    matches: list[dict], min_score: float = MATCH_MIN_SCORE, min_margin: float = MATCH_MIN_MARGIN
) -> str:
    """A registered name, or UNKNOWN / AMBIGUOUS, from scored matches (best first)."""
    if not matches or matches[0]["score"] < min_score:
        return "UNKNOWN"
    runner_up = matches[1]["score"] if len(matches) > 1 else -1.0
    if matches[0]["score"] - runner_up < min_margin:
        return "AMBIGUOUS"
    return matches[0]["name"]


def status_of(name: str) -> str:
    return {"UNKNOWN": "unknown", "AMBIGUOUS": "ambiguous"}.get(name, "identified")


def remove_speaker_clips(folder: Path | None = None) -> None:
    """The pipeline saves each speaker's speech as speaker_clips/speaker_NN.wav for the voice
    match. Once a recording is processed they are copies of a person's voice nobody needs, and
    deleting the session would otherwise leave them on disk."""
    for clip in (folder or AUDIO_SERVICE_DIR / "speaker_clips").glob("speaker_*.wav"):
        clip.unlink(missing_ok=True)


def load_pipeline() -> tuple[Callable[[str], dict], str | None]:
    """(process_audio, note): ``note`` explains when the fallback is in use."""
    # The pipeline loads its models at import time and needs HF_TOKEN, so import lazily.
    sys.path.insert(0, str(AUDIO_SERVICE_DIR))
    try:
        from pipeline import process_audio

        def process(audio_path: str) -> dict:
            try:
                result = process_audio(audio_path)
                with span_scorer(audio_path, voice_scorer()) as score_span:
                    return decide_speakers(result, score_span)
            finally:
                remove_speaker_clips()

        return process, None
    except Exception as error:  # e.g. huggingface_hub GatedRepoError (403)
        reason = str(error).splitlines()[0][:200]
    import speaker_identification  # noqa: F401  (fails here if the voice model can't load)

    note = (
        "Speaker separation (pyannote) is unavailable, so each sentence's voice is matched "
        f"against the enrolled samples instead. Reason: {reason}"
    )
    return process_without_diarization, note


def voice_scorer() -> Identify:
    """Tina's ``identify_speaker`` with each enrolled voice embedded once per recording.

    ``identify_speaker`` calls SpeechBrain's ``verify_files`` per enrolled voice, which embeds
    both clips every time (about 1 s per voice on the server's CPU). The score is the cosine of
    the two embeddings either way, so the numbers are the same (checked in
    eval/listener/collect.py); the same-speaker flag uses the verifier's 0.25."""
    import speaker_identification as si

    model = si.speaker_model
    enrolled = []
    for person_id, person in si.load_registry().items():
        audio = model.load_audio(str(si.ENROLLMENT_DIR / person["audio_file"])).unsqueeze(0)
        enrolled.append((person_id, person["name"], model.encode_batch(audio, normalize=False)))

    def identify(clip: str) -> list[dict]:
        embedding = model.encode_batch(model.load_audio(clip).unsqueeze(0), normalize=False)
        scores = []
        for person_id, name, reference in enrolled:
            score = float(model.similarity(reference, embedding)[0].item())
            scores.append(
                {"person_id": person_id, "name": name, "score": score, "same_speaker": score > 0.25}
            )
        return sorted(scores, key=lambda m: m["score"], reverse=True)

    return identify


def cut_clip(audio: wave.Wave_read, start: float, end: float, path: Path) -> Path:
    rate = audio.getframerate()
    audio.setpos(min(int(start * rate), audio.getnframes()))
    frames = audio.readframes(int((end - start) * rate))
    with wave.open(str(path), "wb") as out:
        out.setparams(audio.getparams())
        out.writeframes(frames)
    return path


@contextmanager
def span_scorer(audio_path: str, identify: Identify) -> Iterator[ScoreSpan]:
    """Score stretches of a WAV recording (the app converts uploads to 16 kHz mono first)."""
    with tempfile.TemporaryDirectory() as tmp, wave.open(audio_path, "rb") as audio:
        count = itertools.count()

        def score_span(start: float, end: float) -> list[dict]:
            return identify(str(cut_clip(audio, start, end, Path(tmp) / f"{next(count)}.wav")))

        yield score_span


def align_words(whisper_segments: list[dict], speaker_turns: list[dict]) -> list[dict]:
    """Split Whisper segments where the diarised speaker changes.

    Tina's ``align_speakers`` gives each whole Whisper segment to the speaker it overlaps
    most, but Whisper's segments often run across a turn change, so the first words of the
    next speaker were credited to the previous one. Here each word goes to the speaker turn
    it overlaps most (or the nearest within ``WORD_GAP_SECONDS``, else UNKNOWN), and runs of
    words with one speaker become segments. A segment without word timings is kept whole."""
    aligned = []
    for seg in whisper_segments:
        words = seg.get("words") or []
        if not words:
            speaker = _turn_at(seg["start"], seg["end"], speaker_turns)
            aligned.append({k: seg[k] for k in ("start", "end", "text")} | {"speaker": speaker})
            continue
        run = None
        for word in words:
            speaker = _turn_at(word["start"], word["end"], speaker_turns)
            if run and run["speaker"] == speaker:
                run["end"], run["text"] = word["end"], run["text"] + word["word"]
            else:
                run = {"start": word["start"], "end": word["end"], "speaker": speaker}
                run["text"] = word["word"]
                aligned.append(run)
    for seg in aligned:
        seg["text"] = seg["text"].strip()
    return aligned


def _turn_at(start: float, end: float, turns: list[dict]) -> str:
    best, best_overlap, nearest, nearest_gap = "UNKNOWN", 0.0, "UNKNOWN", WORD_GAP_SECONDS
    for turn in turns:
        shared = min(end, turn["end"]) - max(start, turn["start"])
        if shared > best_overlap:
            best, best_overlap = turn["speaker"], shared
        gap = max(turn["start"] - end, start - turn["end"])
        if shared <= 0 and gap <= nearest_gap:
            nearest, nearest_gap = turn["speaker"], gap
    return best if best_overlap > 0 else nearest


def veto(
    segment: dict,
    own_matches: list[dict] | None,
    min_score: float = MATCH_MIN_SCORE,
    min_margin: float = MATCH_MIN_MARGIN,
) -> str:
    """``segment["speaker"]`` (its diarised speaker's name), unless the segment's own clip
    clearly names a different enrolled voice: then AMBIGUOUS. Diarisation sometimes merges two
    similar voices into one speaker, which then gets one name for both people's words."""
    name = segment["speaker"]
    if name in ("UNKNOWN", "AMBIGUOUS") or not own_matches:
        return name
    if segment["end"] - segment["start"] < MIN_SEGMENT_SECONDS:
        return name
    own = best_match(own_matches, min_score, min_margin)
    return "AMBIGUOUS" if own not in ("UNKNOWN", "AMBIGUOUS", name) else name


def turn_runs(segments: list[dict]) -> list[list[int]]:
    """Indexes of the segments, grouped into runs of consecutive segments with one speaker."""
    runs: list[list[int]] = []
    for n, seg in enumerate(segments):
        if runs and segments[runs[-1][-1]]["speaker"] == seg["speaker"]:
            runs[-1].append(n)
        else:
            runs.append([n])
    return runs


def decide_speakers(result: dict, score_span: ScoreSpan) -> dict:
    """Re-decide who said what in the output of Tina's ``process_audio``:

    1. words to speakers: with word timings and the diarisation turns, ``align_words``
       (otherwise the pipeline's own per-segment alignment);
    2. each diarised speaker named from the scores her pipeline recorded, with ``best_match``
       rather than her rule (her decision is kept under ``voice_matches[label]["verifier"]``);
    3. ``veto``: each line of at least ``MIN_SEGMENT_SECONDS`` is scored on its own clip, and
       one that clearly names someone else becomes AMBIGUOUS;
    4. the same check on each whole turn (``turn_runs``: consecutive lines of one diarised
       speaker), so a turn Whisper cut into lines too short to check one by one is still
       checked. A line is credited only if neither its own voice nor its turn's names
       someone else.

    The scores behind every decision stay in the result for the Listener inspector.
    ``score_span(start, end)`` scores that stretch of the recording (``span_scorer``)."""
    from speaker_mapping import merge_consecutive_speaker_segments

    names, speakers = {}, {}
    for label, identity in result.get("voice_matches", {}).items():
        matches = sorted(identity.get("matches", []), key=lambda m: m["score"], reverse=True)
        names[label] = best_match(matches)
        speakers[label] = {
            **identity,
            "matches": matches,
            "name": names[label],
            "status": status_of(names[label]),
            "verifier": {"name": identity.get("name"), "status": identity.get("status")},
        }
    turns = result.get("speaker_segments")
    has_words = any(seg.get("words") for seg in result.get("whisper_segments", []))
    if turns is not None and has_words:
        aligned = align_words(result["whisper_segments"], turns)
    else:
        aligned = [dict(seg) for seg in result.get("aligned_segments", [])]

    def checkable(name: str, start: float, end: float) -> bool:
        return name not in ("UNKNOWN", "AMBIGUOUS") and end - start >= MIN_SEGMENT_SECONDS

    # A turn of several lines is also scored as a whole (one line is checked on its own below).
    turn_of, turn_checks = {}, {}
    for run in turn_runs(aligned):
        first, last = aligned[run[0]], aligned[run[-1]]
        turn = {"start": first["start"], "end": last["end"]}
        name = names.get(first["speaker"], "UNKNOWN")
        if len(run) > 1 and checkable(name, turn["start"], turn["end"]):
            turn_checks[run[0]] = {**turn, "matches": score_span(turn["start"], turn["end"])}
        turn_of.update(dict.fromkeys(run, run[0]))

    segments = []
    for n, seg in enumerate(aligned):
        label = seg["speaker"]
        named = {**seg, "speaker": names.get(label, "UNKNOWN")}
        own = None
        if checkable(named["speaker"], seg["start"], seg["end"]):
            own = score_span(seg["start"], seg["end"])
        name = veto(named, own)
        turn = turn_checks.get(turn_of[n])
        if turn and name == named["speaker"]:
            name = veto({**named, "start": turn["start"], "end": turn["end"]}, turn["matches"])
        seg["voice_match"] = {
            "name": name,
            "status": "vetoed" if name != named["speaker"] else status_of(name),
            "speaker_name": named["speaker"],
            # The line's own scores when it was checked, else its diarised speaker's.
            "matches": own if own is not None else speakers.get(label, {}).get("matches", []),
            "scores_from": "line" if own is not None else "speaker",
            # Its whole turn's scores, when the turn has several lines and was checked.
            "turn": turn,
        }
        segments.append(
            {
                "start": seg["start"],
                "end": seg["end"],
                "speaker": name,
                "original_speaker": label,
                "text": seg["text"],
            }
        )
    return {
        **result,
        "pipeline_aligned_segments": result.get("aligned_segments", []),
        "aligned_segments": aligned,
        "voice_matches": speakers,
        "speaker_identities": names,
        "matching": {"minScore": MATCH_MIN_SCORE, "minMargin": MATCH_MIN_MARGIN, "per": "speaker"},
        "segments": merge_consecutive_speaker_segments(segments),
    }


def process_without_diarization(audio_path: str) -> dict:
    """Tina's pipeline minus diarization: transcribe, then identify each segment's speaker.
    ``audio_path`` must be a WAV file (the app converts uploads to 16 kHz mono first)."""
    from speaker_mapping import merge_consecutive_speaker_segments

    identify = voice_scorer()
    worker = AUDIO_SERVICE_DIR / "transcription_worker.py"
    done = subprocess.run(
        [sys.executable, str(worker), audio_path], capture_output=True, text=True, check=True
    )
    transcription = json.loads(done.stdout)
    segments = []
    with tempfile.TemporaryDirectory() as tmp, wave.open(audio_path, "rb") as audio:
        for n, seg in enumerate(transcription["segments"]):
            seg = {k: v for k, v in seg.items() if k != "words"}
            speaker = "UNKNOWN"
            identity = {"name": "UNKNOWN", "status": "too_short", "matches": []}
            if seg["end"] - seg["start"] >= MIN_SEGMENT_SECONDS:
                clip = cut_clip(audio, seg["start"], seg["end"], Path(tmp) / f"segment-{n}.wav")
                matches = identify(str(clip))
                speaker = best_match(matches)
                scores = ", ".join(f"{m['name']} {m['score']:.2f}" for m in matches[:3])
                print(f"segment {n}: {speaker} ({scores})", flush=True)
                identity = {"name": speaker, "status": status_of(speaker), "matches": matches}
            segments.append({**seg, "speaker": speaker, "voice_match": identity})
    return {
        "language": transcription["language"],
        "speaker_identities": {},
        # Diagnostics for the Listener inspector; not used by any model.
        "whisper_segments": transcription["segments"],
        "aligned_segments": segments,
        "matching": {"minScore": MATCH_MIN_SCORE, "minMargin": MATCH_MIN_MARGIN, "per": "sentence"},
        "segments": merge_consecutive_speaker_segments(segments),
    }


def screen_injection(text: str) -> str | None:
    """The Listener's last step: does this turn try to instruct the grader? A pattern check on
    the transcribed words ("ignore the rubric", "give me full marks"); a quoted example in a
    taught lesson is told apart from a command. None when nothing is found. The words are never
    changed: the flag travels with the turn to the professor's review, the Judge and the
    Auditor."""
    kind = injection_signal(text)["classification"]
    return None if kind == NONE else kind


def screen_transcript(inputs: AssessmentInputs) -> AssessmentInputs:
    """Screen every turn that is not yet screened, however the transcript got in (a recording,
    a demo seminar, an import). A professor's turns are not graded, so they are left alone."""
    for turn in inputs.transcript.turns:
        if turn.injection is None and turn.speaker.kind != "professor":
            turn.injection = screen_injection(turn.text)
    return inputs


def to_transcript(
    result: dict,
    ids_by_name: dict[str, str],
    version: str,
    professor_names: frozenset[str] | set[str] = frozenset(),
) -> Transcript:
    """``ids_by_name`` maps a registered student's display name to their roster ID;
    ``professor_names`` are registered professors' names, whose turns become professor turns."""
    turns = []
    for n, seg in enumerate(result["segments"], start=1):
        start = int(seg["start"] * 1000)
        end = max(int(seg["end"] * 1000), start + 1)
        student_id = ids_by_name.get(seg["speaker"])
        if seg["speaker"] in professor_names:
            speaker = {"kind": "professor", "label": seg["speaker"]}
        elif student_id:
            speaker = {"kind": "student", "studentId": student_id}
        else:
            label = "Ambiguous speaker" if seg["speaker"] == "AMBIGUOUS" else "Unknown speaker"
            speaker = {
                "kind": "uncertain",
                "label": label,
                "candidateStudentIds": [],
                "reason": "Voice did not match exactly one registered student",
            }
        turns.append(
            {
                "id": f"turn-{n:03d}",
                "startMs": start,
                "endMs": end,
                "speaker": speaker,
                "text": seg["text"] or "(inaudible)",
                # A professor's words are not graded, so only other speakers are screened.
                "injection": None
                if speaker["kind"] == "professor"
                else screen_injection(seg["text"] or ""),
            }
        )
    return Transcript(version=version, reviewStatus="reviewed", turns=turns)
