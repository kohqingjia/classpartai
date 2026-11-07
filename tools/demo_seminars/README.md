# Demo seminars

Seven scripted mock classes, one per edge case, for the presentation (`scripts.json`):

1. everyone takes part
2. one student never speaks
3. nobody answers
4. a wrong claim, then a correction
5. a spoken prompt injection
6. one student dominates
7. a guest who isn't on the class list

In each one the professor speaks the most.

- **Voices:** every line except the guest's is cloned with F5-TTS from the voice samples we enrolled. That includes Prof Wynter, who agreed to her voice being used. The guest is macOS `say` and isn't enrolled, so the Listener must leave their lines unknown.
- **Audio:** the finished demos are committed in `data/demo-seminars/`, with the team's agreement, and also live on the server in `DATA_DIR/demo-seminars`.

## Make them

```sh
sh say_lines.sh lines/                         # Mac: the guest's lines
python clone.py <enrolled samples> lines/      # F5-TTS: the students' lines (slow on CPU)
python assemble.py lines/ demo-seminars/       # one WAV per demo + its timed script
```

Copy `demo-seminars/` to `DATA_DIR/demo-seminars` on the server. In the app, go to New class session → 🎭 Demo seminars and press Transcribe on a demo. It runs the real Listener, then you create the session as usual. Step ① Record shows the recording with the script underneath, and a ▶ on each line.
