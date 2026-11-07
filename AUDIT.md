# ClassPart AI: what is still open

Branch `improvements`. Gaps only; everything already done has been removed. Measured against the
course brief: working agentic system, evaluation pipeline, quantitative and qualitative analysis,
at least two compared alternatives, risks and mitigations, reproducibility. Report, written
reflection and contribution notes are out of scope for now.

Nothing has been run against a live model (the OpenAI key is off), so every statement about
behaviour comes from the code or the committed results.

## 1. Evaluation

| Agent | Missing |
|---|---|
| Judge | Never run. The answer key (`data/is469/judge_labels.jsonl`) is my draft, all `reviewed: false`, so a run today would measure my draft, not human agreement. |
| Auditor | Evaluated offline with scripted doubles only. "Judge alone vs Judge + Auditor" is covered only indirectly by two guardrail runs. |
| Feedback | No evaluation: quality, privacy, "no observed contribution" wording, trait claims, faithfulness to the findings. |
| Summary agent | No evaluation, and not in the README's evaluation or workflow tables. |
| Listener | Injection screen has a labelled set but no held-out one. All audio is scripted with synthetic or cloned voices; no real classroom noise, overlap or accents. |
| Research | One model, one run, 20 items. The web route is untested (no search key). `answers_question_ok` (35%) measures a definition that disagrees with the labels, not the agent. |
| Whole system | No end-to-end evaluation: recording in, final scores and feedback out, against what a person would give. |

Method gaps that apply to every evaluation:
- **One model.** Everything is `gpt-5-mini`. No model, prompt or reasoning-effort comparison.
- **One run each, no variance.** Guardrail cases 05 and 06 flip between runs (8/10, then 10/10).
  Report a mean and range over N runs.
- **Small samples, no intervals.** 20 items, 20 items, 7 clips. State it; a bootstrap interval is a
  few lines.
- **No prompt/config stamp on results and no compare command.** This is what "change a prompt, see
  what changed" needs.
- **Independent labels.** A second person should score a subset of the Judge key blind.
- **Cost sample is incomplete.** `eval/results/cost-measured.json` has no Judge calls and stopped at
  the budget. The cost page now says so and switches to the newest complete run in the ledger once
  one exists. Run one full assessment on the server.
- **Prices.** Only `gpt-5-mini` is checked; the rest of `data/model_prices.json` is a draft.

### Qualitative evaluation: how we do it

The brief asks for running the system on realistic input and analysing the output, not only
metrics. Proposed method, using what already exists:

1. **Cases.** The seven demo seminars are already designed edge cases with scripts: everyone
   speaks, one silent, nobody, a misconception, an injection, one dominant speaker, a guest.
   Run each end to end once.
2. **Read the real outputs** (they are stored, and the Traces tab shows them): the Judge's
   findings and justifications, the Auditor's issues, each Feedback email.
3. **Fixed questions per output**, answered yes/no with a one-line reason: Is every claim
   traceable to the transcript? Is the score fair for what was said? Does the email invent
   anything? Is the tone constructive? Does it leak another student? Was the right thing flagged?
4. **Failure taxonomy.** Tag each wrong output with a cause (misheard, over-credited, hallucinated
   quote, unfair to silence, injection followed, tone). Count them.
5. **Second reader.** A teammate answers the same questions on the same outputs without seeing the
   first reader's answers; report where they differ.
6. **Write-up.** One `eval/results/qualitative-<date>.md` per round: 5 to 10 real outputs, what was
   right, what was wrong, the pattern, and which fix follows. Feeds the Reflection page.

Optional, small to build: a review page where a reader ticks the questions per output and the
result is saved to the database and exported as that markdown. Say if you want it.

## 2. Experiments to add (the "compare two alternatives" requirement)

In order of value for effort:
1. Judge: single structured call vs tool-using agent (the old Judge is in git history).
2. Judge: reasoning-effort and prompt variants (`JUDGE_REASONING_EFFORT` is already a switch).
3. One agent on two model sizes, with cost per point of agreement (the ledger prices each call).
4. Judge with vs without Research evidence (a label-derived bundle already exists).
5. Auditor on vs off over the labelled set: what it catches that `validate_proposal` does not.
6. Injection screen: pattern vs a small model-based check, on a held-out attack set.

## 3. Reproducibility

- `SEED=42` seeds Python and NumPy only. Model calls are not seeded (gpt-5 models reject a
  non-default temperature), so reruns will not reproduce numbers. Say so, rely on repeats.
- One documented command sequence that reproduces every table, with expected cost and time.

## 4. Risks that remain

- **LLM-judge bias.** Nothing tests that the Judge is not rewarding fluency or length.
- **Confidence is unchecked.** Nothing tests that "low" confidence goes with being wrong.
- **Fallback path.** Without the gated pyannote model the Listener uses a weaker path; the
  evaluation numbers are for the diarised path only.

## 5. Architecture notes

- `app.py` is about 2,500 lines (UI, orchestration and wiring). Hardest file to explain or change.
- Two Auditor worlds: `auditor_agent/` has its own contracts and `participation/auditor_bridge.py`
  translates both ways. Document it as a deliberate boundary or consolidate.
- Summary agent (`summary/`, `summary_demo.py` at the root) uses Groq when a key exists; it is a
  fifth agent missing from the README tables.
- `get_student_history` (the Judge's third idea) is deferred.

## 6. Optimisation candidates, for your review (O2 to O4 are done, see below)

Each keeps the agent's decisions. They only reduce turns, repeated input or repeated work. The
numbers come from the one measured run (`cost-measured.json`, incomplete: no Judge, stopped at the
budget), so treat them as direction, not saving. Tick the ones that make sense.

| # | Candidate | Why | Behaviour change |
|---|---|---|---|
| O1 | **Feedback turns.** Let `draft_student_feedback` take a list of students. The Coordinator still decides when and for whom; each student's email is still its own Feedback call. | Today the Coordinator spends one turn per student, and every turn re-sends its growing history. 4 students is 4 turns. | None to what is written; fewer Coordinator turns. |
| O5 | **Feedback gets every evidence bundle for every student.** Send only the bundles that student's findings cite. | Smaller prompt per student, repeated N times. | Possible: the writer could no longer cite a passage it was not sent. Needs a check. |
| O6 | **Research reasoning effort.** An opt-in setting for Research's navigation calls, then measure. | About 80% of Research's output tokens were hidden reasoning (25,792 of 32,113), and Research was 65 of 71 calls. The Coordinator (80%) and Feedback (69%) are similar; those two already have an opt-in setting. | Possible quality change: must be compared on `research_eval.py` first. |
| O7 | **Research does 2 answers per `retrieve_evidence`** (`MAX_RUNS`). A class needs several Coordinator retrieve turns. | Fewer Coordinator turns if one call covered more answers. | Each call runs longer against the 10-minute limit. A trade-off, not a free win. |
| O8 | **Research on answers with no claim.** It searched the course for the two items that need no evidence. | Wasted searches. | Needs an agent-side fix (better instruction), not a hard rule, or it stops being the agent's decision. |
| O9 | **Re-audit only what changed** after a re-score. The Judge already knows which students were revised. | A full audit repeats checks on untouched findings. | None if the Auditor still sees the whole draft for context. To verify in `auditor_bridge.py`. |


## Not verified

- Behaviour, tokens, latency and cost with a real model, including after the Judge optimisation.
- Whether the deployed server has network-level access control.
- The server-only recordings behind the Listener evaluation.
