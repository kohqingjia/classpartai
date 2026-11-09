# Data

Small datasets and evaluation sets live here. Large or licensed files go in `data/raw/` (git-ignored); document where to download them below so others can reproduce the project.

## Sources

### IS469 course materials (the Research agent's default course)

- `is469/schedule.json` (committed): one entry per topic week: date, topic, key concepts, discussion
  prompts, and `materials` filename patterns (`"*Topic7*"`) that link each week to its files. The
  Topic 5–6 deck belongs to both weeks 5 and 6. **The dates are placeholders**: set them to the real
  seminar dates, or to the dates you give the mock recordings.
- `is469/eval_contributions.jsonl` (committed): 20 mock professor-question / student-answer pairs
  written for this project, labelled with the sources Research should search, whether the answer is
  correct, whether it answers the question, and (for some) how the student reasoned and what kind
  of mistake it was, and the topic files holding the gold evidence. Used by
  `eval/research_eval.py`.
- `is469/judge_labels.jsonl` (committed): a human score (0-3, or `null` for insufficient evidence) for
  each rubric criterion of those 20 contributions, whether the Judge should flag the contribution for
  the professor, and a one-line reason. Used by `eval/judge_eval.py`. **Drafts**: every row says
  `"reviewed": false` until a teammate has checked it and flipped it to `true`.
- `is469/week7_seminar.json` (committed): Tasmin's mock Week 7 (Agentic AI) seminar, using the
  lecture's real questions with our team answering: roster, 10-turn transcript and rubric. Its
  documents are left out (they are slide text); the **IS469 Week 7 seminar** button on New class
  session adds the course library's documents, so upload the slides first.
- `raw/is469/` (**git-ignored**): the lecture files themselves, which are the instructor's and are
  not ours to commit. Source: the IS469 course materials (Topic 1–8 decks as `.pptx`/`.pdf`, labs as
  `.ipynb`). Each teammate copies them in, all in one folder; keep one copy of any file downloaded
  twice (e.g. `Topic6_Evaluation_Lab.ipynb` and `Topic6_Evaluation_Lab (2).ipynb`). Then run
  `uv run python -m classpartai.research ingest`.

### Demo seminars and voice samples (our own voices)

- `demo-seminars/`: the scripts of the seven demo seminars, cloned with F5-TTS from our voice
  samples (see `tools/demo_seminars/README.md` for how they are made). Each `NN-name.json` has the
  title, the case it tests and the script it was read from, line by line with start and end times.
  The audio (`NN-name.wav`, 16 kHz mono, 41–95 s) is in our own voices, so it is kept on the
  server (`DATA_DIR/demo-seminars`), not in git.

  | File | Demo |
  |---|---|
  | `01-everyone` | 1 · Agentic RAG: everyone takes part |
  | `02-one-silent` | 2 · Agents: one student never speaks |
  | `03-nobody` | 3 · Evaluation: nobody answers |
  | `04-misconception` | 4 · Training: a wrong claim, then a correction |
  | `05-injection` | 5 · Ethics: a student tries to game the grader |
  | `06-dominant` | 6 · Transformers: one student dominates |
  | `07-guest` | 7 · Fine-tuning: a guest who isn't on the class list |

- `voice-samples/`: the enrolment clip (18–28 s) for each speaker in the demos, used to recognise
  who is speaking. They are real voices, so they are not in git; put them here from the server to
  enrol the same people locally.

<!-- Add further datasets: name, URL, licence, and any preprocessing steps. -->

## Injection cases

`is469/injection_cases.jsonl`: 40 short lines labelled `attack`, `benign` or `quoted_example` (a student discussing an attack). Written by the team, not taken from students. Used by `eval/injection_eval.py`.
