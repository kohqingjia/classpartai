# What is still open

Gaps only; finished work is not listed. Numbers about behaviour come from one incomplete live run
and the committed results.

## 1. Not run yet

| What | What it needs | What I (Claude) do / what you do |
|---|---|---|
| `eval/system_eval.py` | OpenAI key, US$1 to 3 | I run it. It plays the 7 demo seminars through the whole system and writes `system-<stamp>.json/.md` plus `qualitative-<stamp>.md`. |
| `eval/judge_eval.py` | OpenAI key | I run it. The 20 labels in `data/is469/judge_labels.jsonl` are marked reviewed. |
| Qualitative round | the two files above | **You and one teammate**, see below. |
| A full assessment with the cost page | one assessment that finishes inside the 10-minute limit | see "Cost page" below. |

**The qualitative round, step by step.** The automatic checks say whether something is wrong in a way
code can see. They cannot say whether a score was *fair* or an email *kind*; only a person can.
1. After the system run, open `eval/results/qualitative-<stamp>.md`. It lists every student in
   every demo seminar: their findings (scores and why) and the email drafted for them.
2. Under each one are five yes/no questions (is every claim traceable to what they said? is the
   score fair for what was said, not how long or confidently? does the email invent or name someone
   else? is the tone constructive, silence described as not observed? was the right thing flagged
   for the professor?). Tick or leave unticked, one line of why.
3. For anything wrong, write a cause: misheard, over-credited, hallucinated quote, unfair to
   silence, injection followed, or tone.
4. A teammate does the same on a copy **without seeing your answers**. Then count where you
   disagree. That count is the report's honesty check: if two people disagree a lot, the "fair"
   judgement is itself uncertain.
About 7 seminars x 4 students is 28 short reads, roughly an hour each.

**Cost page.** The Monitoring page prices an assessment from real usage events. The only recorded
assessment never finished (it hit the 10-minute limit), so the page extrapolates from an incomplete
sample and says so. Once one assessment completes (after the Research speed-up below), that number
replaces it. Nothing to do on a server; running it locally is enough.

## 2. Method gaps (what the brief's evaluation asks for, in plain words)

- **One run each, no variance.** The same input can score differently on two runs (guardrail cases
  05 and 06 passed once and failed once). One number hides that. Fix: run each eval 3 times, report
  the mean and the lowest/highest. `system_eval.py` and `guardrails.py` need a `--repeat 3` flag.
- **Small samples, no intervals.** With 20 test items, "17 of 20 correct" could easily be 14 or 19
  on another 20. Say "85%, but only 20 items" rather than quoting 85% alone, or add a confidence
  range.
- **No config stamp on results.** A results file does not record which prompts and model produced
  it, so two files cannot be compared fairly. Fix: write model, reasoning effort and a prompt hash in
  every results file, and a small command that diffs two.
- **One labeller.** The Judge's "correct" scores were written by one person. If a second person
  scores 10 of them without looking, we can say how much humans agree with each other, which is the
  ceiling for how well the Judge can be said to agree.
- **One model everywhere** (`gpt-5-mini`), so there is no "model A vs model B" comparison yet.
  Only `gpt-5-mini`'s price is verified.
- Research's `answers_question_ok` (35%) measures a definition that disagrees with the labels, so the
  35% is partly a labelling mismatch, not a bad agent.
- Listener audio is scripted with synthetic voices: no real noise, overlap or accents.
- Injection screen: 20/20 is on a set written together with the screen; it needs items written by
  someone else.

## 3. Experiments still worth adding

Judge single call vs tool-using agent · Judge prompt variants · one agent on two model sizes (cost
per point of agreement) · Judge with vs without Research evidence · Auditor on vs off over the
labelled set · injection screen pattern vs a small model check.
The **Research reasoning-effort experiment** (current vs low, side by side) is being built, see
section 6.

## 4. Code

- `app.py` is about 2,500 lines (UI, orchestration, wiring).
- **Two evidence agents.** The Coordinator can fetch course evidence in two ways, chosen by
  `EVIDENCE_AGENT`: `research` (the Research agent, the default) or `course` (the earlier version
  from Le Yong, `evidence.py`). Only the first is used or evaluated. The second is dead weight unless
  we want to compare them; delete it to cut confusion, or keep it as the comparison baseline.
- **Summary agent not wired in.** `summary/` produces a seminar summary but the Coordinator never
  calls it; it only runs from `summary_demo.py`. Wiring it in as a Coordinator step is queued.

## 5. Optimisation candidates

Each keeps the agent's decisions and only cuts turns or repeated input.

| # | Candidate | Status |
|---|---|---|
| O1 | One `draft_student_feedback` call takes several students | done |
| O8 | Research stops searching for answers that make no claim | done |
| O9 | After a re-score, re-inspect only findings that changed | done |
| O6 | Lower reasoning effort for Research, shown as an experiment with the two runs side by side | being built |
| O5 | Feedback gets only the evidence its student's findings cite | needs a quality check first |
| O7 | Research answers more than two items per `retrieve_evidence` | longer calls against the time limit |

Prompt caching is on automatically at OpenAI; prompts are ordered for it and every call in a session
shares one `prompt_cache_key`. Re-measure the cached share after the first full run.

Prototype scope: login, consent/retention, fairness audits and unit tests for the newest modules
are deliberately left out for now.
