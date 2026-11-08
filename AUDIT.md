# What is still open

Gaps only; finished work is not listed. Nothing has run against a live model yet (the OpenAI key is
off), so everything below about behaviour comes from the code or committed results.

## 1. Not run yet

| What | Blocked on |
|---|---|
| `eval/system_eval.py`: 7 sessions, edge cases, hand-offs, tool-call correctness, email quality (LLM judge), lessons | OpenAI key (US$1 to 3) |
| `eval/judge_eval.py`: Judge against a human key | OpenAI key, and a teammate marking `judge_labels.jsonl` rows `reviewed: true` (today it is my draft) |
| The qualitative round: read the outputs, answer the questions, tag causes | a system run (it writes `qualitative-<stamp>.md`), then two readers |
| One full assessment on the server, so the cost page stops using the incomplete sample | server access |

## 2. Method gaps

- One model (`gpt-5-mini`) everywhere: no model, prompt or reasoning-effort comparison.
- One run each, no variance (guardrail cases 05 and 06 flip between runs). Report mean and range.
- Small samples (20, 20, 7), no intervals.
- No prompt/config stamp on results and no compare command.
- Only one person labelled the Judge key; a second should score a subset blind.
- Only `gpt-5-mini`'s price is verified.
- Research's `answers_question_ok` (35%) measures a definition that disagrees with the labels.
- Listener audio is scripted with synthetic voices: no real noise, overlap or accents.
- Injection screen: its 20/20 is on a set written with it; it needs a held-out set.

## 3. Experiments still worth adding

Judge single call vs tool-using agent · Judge reasoning-effort and prompt variants · one agent on two
model sizes (cost per point of agreement) · Judge with vs without Research evidence · Auditor on vs
off over the labelled set · injection screen pattern vs a small model check.

## 4. Risks that remain

- **No login.** Anyone who can open the app can open any session and **Download data**. Decide what
  protects the deployment, and remove the page once the files are copied.
- **Consent and retention.** Demo voices appear to be team members'; no retention or deletion policy.
- **Fairness.** Voice accuracy across accents or similar voices is unmeasured; so is LLM-judge bias
  toward fluency or length, and whether "low confidence" goes with being wrong.
- **Fallback Listener** (no pyannote token) is weaker than the evaluated path.
- Reruns cannot reproduce numbers exactly: model calls are not seeded.

## 5. Code

- `app.py` is about 2,500 lines (UI, orchestration, wiring).
- Two evidence agents behind `EVIDENCE_AGENT` (Research, and Le Yong's `evidence.py`).
- The Summary agent (`summary/`, `summary_demo.py`) is not wired into the Coordinator.
- Tests to write: the merged Auditor (`participation/auditor.py`), `lessons.py`,
  `feedback_checks.py`, `system_eval.py`.

## 6. Optimisation candidates (nothing applied; tick the ones you want)

Each keeps the agent's decisions and only cuts turns or repeated input. Numbers come from the one
incomplete measured run, so they show direction, not saving.

| # | Candidate | Behaviour change |
|---|---|---|
| O1 | `draft_student_feedback` takes a list of students; each email is still its own Feedback call. Saves one Coordinator turn per student. | None to what is written |
| O5 | Feedback gets only the evidence bundles that student's findings cite. | Possible: needs a check |
| O6 | Opt-in lower reasoning effort for Research (about 80% of its output tokens were hidden reasoning). | Possible: compare on `research_eval.py` first |
| O7 | Research answers more than two items per `retrieve_evidence`. | Longer calls against the 10-minute limit |
| O8 | Research stops searching for answers that make no claim. | Needs a better instruction, not a rule |
| O9 | Re-audit only findings that changed after a re-score. | None if the Auditor still sees the whole draft |

Prompt caching is on automatically at OpenAI; the prompts are ordered for it and every call in a
session shares one `prompt_cache_key`. Re-measure the cached share after the first full run.
