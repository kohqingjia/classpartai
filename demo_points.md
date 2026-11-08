# Demo points

Talking points for the presentation. They used to sit on the How it works page; they are kept here
so that page stays short. Slide references are the IS469 slides: topic · "term" (slide).

## Why it's agentic

- **The Coordinator plans.** No fixed script: it reads each tool's result and picks the next call (inspect the transcript, retrieve evidence, propose scores, audit, draft feedback, request review). A refused call comes back with the reason, and it adapts.
- **Research is agentic RAG.** It writes its own queries, searches with BM25 and vectors fused by Reciprocal Rank Fusion, grades what it finds, searches again if the evidence is weak, and only cites exact excerpts from the course notes.
- **The Judge is an agent too.** It starts with the rubric, each student's own turns and a summary of Research's evidence, scores many students per call with a confidence, and fetches more turns or a full evidence bundle only when it needs them. It flags what the professor should check, and a revision after the audit re-scores only the students the Auditor raised.
- **Verify first, judge last.** Every score the Judge saves must pass deterministic validation (right students, cited turns that exist); a student who breaks a rule is refused with the reason. Then the Auditor checks support, attribution and uncertainty before anything reaches the professor.
- **Bounded.** Every run has a budget (96 model calls, 108 tool calls, 500k tokens, 900 s) and stops cleanly when it runs out.
- **Watched.** Every model call's tokens, time and estimated cost, and every step of every run, are recorded (the usage ledger). The Monitoring page shows them.

## Mapped to IS469, in the course's words

| Part | What it does here | Course term |
|---|---|---|
| Listener | Whisper `base`, an encoder-decoder transformer, int8-quantised on CPU and decoded with beam search (5 beams); pyannote splits the voices; ECAPA voice embeddings compared by cosine similarity, named only above 0.35 and 0.10 clear of the runner-up; each line screened for words aimed at the grader | 2 · "Encoder", "Decoder" (S19); 5 · "Beam search" (S7); 4 · "Quantisation" int8 (S46); 1 · "Cosine similarity … measures the angle, not the magnitude" (S30) |
| Coordinator | A model in a loop with six tools and a stop condition; it calls Research, the Judge and the Auditor as tools; one budget for everything (96 model calls, 500k tokens, 900 s); no approve or send tool | 7 · "an agent = an LLM … + a harness" (S3); "Perceive → Plan → Act → Observe" (S13); "The supervisor pattern" (S47); "human-in-the-loop checkpoints" (S48) |
| Research | Routes to the course notes, the web or nowhere; hybrid search: BM25 and embeddings fused with RRF (k = 60); grades what it finds and rewrites the query when evidence is weak, at most twice; cites only verbatim quotes | 8 · "Agentic RAG makes retrieval a TOOL" (S44); "Plan → Search → Judge → Re-query → Answer" (S47); "Routing", "Self-correction (CRAG …)" (S48); "Hybrid search", "Query rewriting" (S39); "Rank fusion (RRF)" (S37); "Grounding rule" (S42) |
| Judge | Scores each student on an explicit rubric with three tools; every score passes deterministic checks before it is saved; confidence and flags for the professor; a separate reasoning-effort setting (`JUDGE_REASONING_EFFORT`) | 6 · "LLM-as-judge" with an "explicit rubric" (S68); "Verify first, judge only what you can't check" (S66); 7 · "effort / thinking dial" (S41) |
| Auditor | A second agent that checks the Judge with six read-only tools: compares similar answers, verifies every citation, checks scores against speaking time, can ask for one re-score, never changes a score; the Listener's injection flag and a rationale aimed at the grader are checked before the model runs | 6 · "programmatic check → verifiable reward → LLM-judge → human" (S66); 7 · "Reflexion & self-critique", "Verify-then-continue" (S37) |
| Feedback writer | One structured model call per student, then rule checks (no classmate named, silence described as not observed, no judgement of ability); a broken rule is sent back once and becomes a lesson for the next email. Deliberately not an agent: it needs no tools | 7 · "Teardown test: a single … call behind a nice UI is NOT an agent" (S63) |
| Approve and send | The professor approves one exact version (SHA-256 of content and recipients); code, not a model, sends it | 9 · "Excessive agency" (S48); "Six controls for agents" (S57, below) |
| Monitoring and evals | Every model call's tokens, latency and cost, and a trace of every step; eval scripts for each agent | 7 · "Evaluate the trajectory" (S54), "Observability & tracing" (S57); 6 · "treat evaluation as a first-class artifact" (S76) |

## How it meets the project brief

| The brief asks for | Where it is |
|---|---|
| Integrates at least two substantial topics | Six: transformers (2), evaluation (5-6), agents and harness (7), agentic RAG (8), ethics and guardrails (9), embeddings (1). See the table above |
| End-to-end implementation with an evaluation pipeline | Recording → transcript → assessment → approval → email, in this app; `eval/` scripts for the Listener, Research, Judge, guardrails and cost |
| Evidence of debugging and validation | Hundreds of automated tests on every pull request; the fixes listed under the Reflection & risks page, each with a regression test |
| Quantitative metrics | Listener: wrong-speaker lines, word error rate. Research: correctness, context precision. Guardrails: attacks caught. Cost and latency per run. Task success of the seven demo runs. See Evaluation |
| Qualitative analysis | Seven demo seminars in our own voices: everyone takes part, a silent student, nobody answers, a wrong claim, a student gaming the grader, one student dominating, a guest |
| Compares at least two alternatives | Single-pass RAG vs the Research agent; Listener before and after its fixes; Auditor tool descriptions, one change at a time; the software against a teaching assistant |
| Reflection, and a direction for future work | The Reflection & risks page: what worked, what did not, what is next |
| Risks and mitigations | Guardrails and Agentic controls (How it works); the Reflection & risks page |
| Reproducible: repository, README, seeds, config | Public repository with a README; `SEED=42`; `.env.example`; every result in `eval/results` names the run that produced it |
| Good teamwork, not disparate pieces | One workflow: Tina's Listener feeds the Coordinator Le Yong designed, which calls Tasmin's Research, Saurabh's Judge and Le Yong's Auditor |
