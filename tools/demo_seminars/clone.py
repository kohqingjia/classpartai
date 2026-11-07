"""Clone the students' lines with F5-TTS, from the voice samples they enrolled.

    python clone.py <samples dir> <out dir> [nfe steps, default 32]

<samples dir> holds the enrolled samples (audio-service/enrollments on the server); each is cut
to its first sentence(s), whose words are scripts.json's ref_text. Needs f5-tts, torch,
torchaudio, soundfile and ffmpeg. On a 4-core CPU a 5-second line takes about 2.5 minutes.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import soundfile as sf
import torch
import torchaudio


def _load(path, *args, **kwargs):  # torchcodec in this CPU build is broken; read with soundfile
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    return torch.from_numpy(data.T.copy()), rate


torchaudio.load = _load
from f5_tts.api import F5TTS  # noqa: E402

script = json.loads((Path(__file__).parent / "scripts.json").read_text())
voices = script["voices"]
samples, out = Path(sys.argv[1]), Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
nfe = int(sys.argv[3]) if len(sys.argv) > 3 else 32
for voice in voices.values():  # the reference clip: the sample's first sentence(s)
    if voice["kind"] == "clone":
        clip = out / f"ref-{voice['sample']}"
        cmd = ["ffmpeg", "-v", "error", "-y", "-ss", str(voice.get("clip_start", 0))]
        cmd += ["-i", str(samples / voice["sample"])]
        subprocess.run([*cmd, "-t", str(voice["clip_seconds"]), str(clip)], check=True)
        voice["ref"] = clip

tts = F5TTS(model="F5TTS_v1_Base", device="cpu")
for session in script["sessions"]:
    for i, (who, text) in enumerate(session["lines"]):
        if voices[who]["kind"] != "clone":
            continue
        target = out / f"{session['id']}-{i:02d}.wav"
        if target.exists():
            continue
        start = time.time()
        tts.infer(
            ref_file=str(voices[who]["ref"]),
            ref_text=voices[who].get("ref_text", ""),
            gen_text=text,
            file_wave=str(target),
            nfe_step=nfe,
            seed=7,
        )
        print(f"{target.name} {time.time() - start:.0f}s", flush=True)
print("done", flush=True)
