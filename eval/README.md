# Evaluation

Scripts that score the system. Results go to `eval/results/` and show on the app's **Evaluation**
and **Monitoring → Before & after** pages. Nothing runs automatically: you run a script, it writes
a result file. Each script reads its seed and model from `classpartai.config`.

## Which kind of evaluation lives where

| Kind (from the brief) | Where | Agent |
|---|---|---|
| Accuracy / F1 | `listener/compare.py` (who-spoke accuracy, word error rate) · `injection_eval.py` (precision, recall) · `research_eval.py` (correctness, context precision) | Listener, Research |
| Rubric-based LLM-as-judge | the Feedback email scored faithful / constructive / specific by a second model: `FEEDBACK_JUDGE` (`feedback_checks.py`), reported by `system_eval.py` · `judge_eval.py` (the Judge itself against human scores: Spearman, kappa) | Feedback, Judge |
| Latency and cost | the usage ledger: every script above reports calls, tokens, dollars and seconds; **Monitoring** shows them per agent | all |
| Agentic: task success | `system_eval.py` (finished, everyone covered, edge case handled, nothing sent) · `guardrails/run.py` (attacks caught) | Coordinator, system |
| Agentic: tool-call correctness | `system_eval.py` (tool calls right first time, per agent) · `judge_eval.py` (rules passed first try, scoring calls) | all tool-using agents |
| Custom eval | `guardrails/run.py` · the edge-case and hand-off checks in `system_eval.py` · the Feedback rule checks | Auditor, system |
| Qualitative analysis | `system_eval.py` writes `qualitative-<stamp>.md`: the real outputs with the questions to answer and a cause to tag | system |

## They feed back to the agent

A check that finds a mistake leaves a **lesson** (`src/classpartai/lessons.py`), kept with the
session. The next call to that agent in the session opens with `earlierChecks`, so the second
student's email does not repeat the first's mistake.

| Agent | What leaves a lesson |
|---|---|
| Feedback | a rule broken (names a classmate, writes a turn ID, silence not stated, judges the person), a weak rubric score, a validation refusal. The draft is sent back once. |
| Judge | a score the rules refused |
| Auditor | a tool call refused |

## Scripts

| Script | Measures | Needs |
|---|---|---|
| `system_eval.py` | the seven demo seminars, transcript to emails, every agent | OpenAI key (US$1 to 3) |
| `guardrails/run.py` | ten attack cases through the whole workflow | OpenAI key (about US$1) |
| `research_eval.py` | single-pass vs agentic RAG on 20 labelled answers (`--documents` for the real slides) | OpenAI key |
| `judge_eval.py` | Judge vs a human key, and how it got there | OpenAI key |
| `injection_eval.py` | injection screen on 40 labelled lines | nothing |
| `listener/collect.py`, `listener/compare.py` | who-spoke accuracy and word error rate (collect runs the models once on the server; compare is offline) | server, then nothing |
| `cost_measure.py <run id>` | what one real run cost, by agent | the server's database |

Judge labels (`data/is469/judge_labels.jsonl`) are drafts until marked `"reviewed": true`.
