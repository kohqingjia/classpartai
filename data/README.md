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
- `raw/is469/` (**git-ignored**): the lecture files themselves, which are the instructor's and are
  not ours to commit. Source: the IS469 course materials (Topic 1–8 decks as `.pptx`/`.pdf`, labs as
  `.ipynb`). Each teammate copies them in, all in one folder; keep one copy of any file downloaded
  twice (e.g. `Topic6_Evaluation_Lab.ipynb` and `Topic6_Evaluation_Lab (2).ipynb`). Then run
  `uv run python -m classpartai.research ingest`.

<!-- Add further datasets: name, URL, licence, and any preprocessing steps. -->
