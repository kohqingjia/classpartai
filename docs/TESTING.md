# Testing the whole workflow, by hand

How to run ClassPart AI end to end and what to look at. This is for trying the system and
collecting evidence, not for the unit tests (`uv run pytest`).

## What you need

| Need | For | Where |
|---|---|---|
| `OPENAI_API_KEY` in `.env` | every model call (Coordinator, Research, Judge, Auditor, Feedback) | `.env.example` |
| `HF_TOKEN` (account has accepted the pyannote terms) | speaker separation; without it the Listener falls back to matching each sentence to a voice | `.env.example` |
| `AGENTMAIL_API_KEY`, `EMAIL_TEST_RECIPIENT` | actually sending the emails; test mode sends everything to that one inbox | `.env.example` |
| The course slides, uploaded in **Course library** | evidence the Research agent can quote (the sample session carries its own small set) | the app |
| Audio | only for the Listener path (C below) | see "Getting the audio" |

Start the app with `uv run streamlit run app.py` (http://localhost:8501). Open **Monitoring**
beside it: every model call, its tokens and its cost appear there as the run goes.

## Pick a path

### A. Everything except the audio (fastest, needs only the OpenAI key)

1. **New class session → Skip to the demo transcript.** This opens a session at step 3 with a
   ready-made transcript, four students and a rubric.
2. Step **③ AI assessment → Generate assessment.** Watch the agents work. Nothing is sent.
3. Open the agent tabs (Coordinator, Research, Judge, Auditor, Feedback writer) to see each one's
   inputs, tool calls and outputs.
4. Step **④ Approve**: read each email preview, tick the box, approve.
5. Step **⑤ Send**: with no AgentMail key this stays a preview; with one, the emails go to
   `EMAIL_TEST_RECIPIENT`.

Also available on the same page: **IS469 Week 7 seminar** (needs the slides in the Course
library) and **Le Yong's fixture**.

### B. Try an attack without audio

1. **New class session → Import a session file (JSON)**, choose a file from
   `eval/guardrails/cases/` (for example `01-direct-injection.json`).
2. Step **② Who spoke?** shows a yellow warning naming the flagged line. This is the Listener's
   injection screen working before any agent has read the text.
3. Generate the assessment. The Judge tab shows the line flagged for the professor and scored on
   its content only; the Auditor tab lists the matching issue.

### C. The full path from audio

1. **New class session → ▶ Use the demo recording** (a 48-second mock seminar in
   `data/demo_audio/`), or upload any WAV, MP3 or M4A.
2. **Class & voices** needs one professor and at least one student with a voice sample; the demo
   recording enrols its own synthetic voices.
3. Continue as in path A from step ② on.

The seven scripted demo seminars (everyone speaks, one silent, nobody speaks, a misconception,
an injection, one dominant speaker, a guest) have their scripts in `data/demo-seminars/`. The
audio is in our own voices, so it is not in git: get the `.wav` files from the server's
`DATA_DIR/demo-seminars`, put them next to the scripts, and copy the folder once, since the app
reads it from `var/demo-seminars/`:

```bash
cp -r data/demo-seminars var/demo-seminars     # PowerShell: Copy-Item -Recurse data\demo-seminars var\
```

The first run downloads the speech models (several minutes).

### D. Run the evaluations

```bash
uv run python eval/injection_eval.py       # no key, no cost: attacks caught vs false alarms
uv run python eval/listener/compare.py     # no key: scores the Listener offline from its cache
uv run python eval/guardrails/run.py       # key: 10 attack cases through the real workflow (~US$1)
uv run python eval/system_eval.py          # key: 7 demo seminars, transcript to emails, every agent
uv run python eval/research_eval.py        # key: single-pass vs agentic RAG (20 items)
uv run python eval/judge_eval.py           # key: Judge agreement with the 20 hand-scored answers
```

Results land in `eval/results/` and appear on the **Evaluation** page. The Judge key is a draft
until the team marks `data/is469/judge_labels.jsonl` rows `"reviewed": true`.

## What to check, and what "good" looks like

| Where | Check | Expect |
|---|---|---|
| Monitoring → by agent | model calls per assessment | Judge about 1; Feedback one per student who spoke (none for a silent student); Coordinator single digits; Research the most (about 25 per investigation) |
| Monitoring → traces | pick the latest run | steps in order: retrieve evidence, judge, audit, feedback, review; no repeated refusals |
| Judge tab | each finding | score within the range, the student's own turns cited, confidence shown, flags for anything odd |
| Auditor tab | issues | citations verified; the Listener's injection flag listed for an attack |
| Approve → email preview | wording | quotes of what the student said, never "turn-003"; course references listed once; no other student named |
| Send | recipients | with test mode on, every email goes to the one test inbox |

If a run ends "needs review" with a stop reason, that is a safe stop, not a crash: the reason is on
the Coordinator tab.

## Getting the data from the deployed server

Open **Download data**, tick what you need, prepare the zip, then put everything in place:

```bash
uv run python tools/unpack_download.py classpartai-data.zip     # --force to overwrite
```

Tick **Course library** (the slides Research quotes: without it the evidence agents have nothing
to cite), **Demo seminars**, and, for the Listener on your own machine, **Class list** and
**Enrolled voice samples**. Voices, recordings, the class list and the database are personal data:
keep the zip off shared drives.

No voice samples yet? `uv run python tools/seed_demo_voices.py` enrols the five demo speakers from
`data/voice-samples/` (not in git: copy the clips there from the server first) so the demo seminars can go through the Listener.
