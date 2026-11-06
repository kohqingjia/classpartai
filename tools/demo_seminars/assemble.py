"""Join each demo's lines into one recording and write its timed script.

    python assemble.py <lines dir> <out dir>

<lines dir> holds <session id>-<line nn>.wav for every line (the professor's and guest's from
say_lines.sh, the students' from clone.py) and enrol-prof.wav. <out dir> becomes
DATA_DIR/demo-seminars on the server (see src/classpartai/demo_seminars.py).
Needs numpy and soundfile.
"""

import json
import random
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

RATE = 16000
HERE = Path(__file__).parent


def load(path: Path) -> np.ndarray:
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    audio = audio.mean(axis=1)
    if rate != RATE:  # F5-TTS writes 24 kHz
        n = round(len(audio) * RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio)
    peak = np.abs(audio).max() or 1.0
    return (audio / peak * 0.6).astype(np.float32)  # same loudness for every speaker


def main(lines_dir: Path, out: Path) -> None:
    script = json.loads((HERE / "scripts.json").read_text())
    voices = script["voices"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "voices").mkdir(exist_ok=True)
    prof = voices["prof"]
    sf.write(out / "voices" / "prof-lim.wav", load(lines_dir / "enrol-prof.wav"), RATE)
    (out / "voices.json").write_text(
        json.dumps(
            [
                {
                    "personId": prof["personId"],
                    "name": prof["name"],
                    "role": "professor",
                    "file": "prof-lim.wav",
                }
            ],
            indent=2,
        )
    )
    rng = random.Random(469)
    for session in script["sessions"]:
        chunks, timed, clock = [np.zeros(int(0.8 * RATE), np.float32)], [], 0.8
        for i, (who, text) in enumerate(session["lines"]):
            audio = load(lines_dir / f"{session['id']}-{i:02d}.wav")
            timed.append(
                {
                    "speaker": voices[who]["display"],
                    "text": text,
                    "start": round(clock, 2),
                    "end": round(clock + len(audio) / RATE, 2),
                }
            )
            gap = rng.uniform(0.7, 1.4)  # a natural pause between speakers
            chunks += [audio, np.zeros(int(gap * RATE), np.float32)]
            clock += len(audio) / RATE + gap
        sf.write(out / f"{session['id']}.wav", np.concatenate(chunks), RATE, subtype="PCM_16")
        (out / f"{session['id']}.json").write_text(
            json.dumps(
                {
                    "id": session["id"],
                    "title": session["title"],
                    "case": session["case"],
                    "lines": timed,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        print(f"{session['id']}: {clock:.0f} s, {len(timed)} lines")


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
