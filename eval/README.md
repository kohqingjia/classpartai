# Evaluation

Scripts that score the system, and the results they produce (`eval/results/`). Each script should read its config and seed from `classpartai.config` so results are reproducible.

- `research_eval.py`: ② Research, single-pass RAG (`research/baseline.py`) vs the agentic
  `ResearchAgent`, on the 20 labelled items in `data/is469/eval_contributions.jsonl`, scored by
  `research/evaluate.py`. It searches the lecture-file index, or with `--documents` a course
  library's `documents.json` (what the app searches), and meters every OpenAI call for tokens and
  cost (`--max-usd` stops the run once that much is spent). It writes a Markdown table and a JSON
  with each item's scores, verdicts and evidence; saved quotes are cut to 25 words, since the
  slides are the instructor's.
  - [`results/research-is469-library.md`](results/research-is469-library.md): the run on the IS469
    slides in the deployed app's course library (7 decks/labs, 353 chunks; `gpt-5-mini`, no web
    search key, so the one web-labelled item, i17, cannot route correctly). Reading it:
    - Agentic is right on correctness slightly more often (0.94 vs 0.88: it verifies i14 and i18,
      where single-pass stays unverified) and has higher context precision (0.94 vs 0.88), at
      about 6x the cost and 5x the time per item (US$0.025 and 113 s vs US$0.004 and 22 s).
    - `answers_question_ok` is low (0.35) because the agent derives it from expected-point
      coverage: a wrong answer covers no expected points, so it gets "no", where the labels say
      a wrong answer still answers the question ("yes"). The labels and the definition disagree.
    - It still searched the course for the two items that need no evidence (i01, i02).
- `guardrails/run.py`: adversarial cases (`guardrails/cases/`, fictional) through the real
  assessment workflow; reports what the guardrails catch. Cases and checks:
  `src/classpartai/participation/adversarial.py`; model-free tests: `tests/test_guardrails.py`.
  - [`results/guardrails-20261107-000458.md`](results/guardrails-20261107-000458.md): the run
    on `gpt-5-mini` (8/10 caught, US$0.95).
