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
  - [`results/guardrails-20261107-010611.md`](results/guardrails-20261107-010611.md): `gpt-5-mini`
    on main with the Auditor agent (#46): 10/10 caught, US$0.96.
  - [`results/guardrails-20261107-000458.md`](results/guardrails-20261107-000458.md): the same
    cases on the code before #46 (single-call model audit): 8/10, US$0.95. 05 (name swap) and 06
    (uncertain speaker) failed there, so they fail in one of two runs: model variance, not fixed.
- `listener/`: ① Listener accuracy on the 7 scripted demo seminars (their recordings and timed
  scripts are on the server only). `collect.py` runs the real models once in the app container
  (Tina's `process_audio`, plus each Whisper segment's and each script line's voice scores
  against every enrolled voice, Whisper size/beam variants, and word timings) and caches it in
  `listener/cache/`; `compare.py` then scores configurations offline from that cache (no
  models): WER against the script, and per script line whether the right person, the wrong
  person or nobody was credited. Scoring rules: `src/classpartai/listener_eval.py`; tests:
  `tests/test_listener_eval.py`.
  - [`results/listener-20261107.md`](results/listener-20261107.md): Tina's rule left 8/26
    student lines unattributed; naming each diarised speaker by score/margin fixed that but
    credited one Tasmin line to Tina (pyannote merged the two); aligning words to speaker turns
    plus a per-line voice veto (now the app's Listener, `decide_speakers`) credits no line to
    the wrong student, gets 25/26 student and 36/36 professor lines right, and cuts students'
    speech given to the professor from 7.6 s to 0.1 s. WER 3.3% (Whisper base, beam 5); small
    2.4% at 2.5x the transcription time.
