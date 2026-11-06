#!/bin/sh
# The professor's and guest's lines (and the professor's voice sample) with macOS `say`.
#   sh say_lines.sh <out dir>
set -e
OUT=${1:?out dir}; HERE=$(dirname "$0"); mkdir -p "$OUT"
python3 - "$HERE/scripts.json" "$OUT" <<'PY'
import json, subprocess, sys
script, out = json.load(open(sys.argv[1])), sys.argv[2]
voices = script["voices"]
READING = ("Good morning. My name is on the class list, and this is my voice sample for "
    "ClassPart AI. Yesterday I read the slides about retrieval, then tested a quick search over "
    "six thick notebooks. The cheerful zebra jumped over a pile of orange boxes while we argued "
    "about whether agents should search again or stop. Thank you for listening.")
def say(who, text, name):
    v = voices[who]
    subprocess.run(["say", "-v", v["voice"], "-r", str(v["rate"]), "-o", f"{out}/{name}.aiff", text], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{out}/{name}.aiff", "-ar", "16000", "-ac", "1", f"{out}/{name}.wav"], check=True)
    subprocess.run(["rm", f"{out}/{name}.aiff"], check=True)
say("prof", READING, "enrol-prof")
for s in script["sessions"]:
    for i, (who, text) in enumerate(s["lines"]):
        if voices[who]["kind"] == "say":
            say(who, text, f"{s['id']}-{i:02d}")
PY
