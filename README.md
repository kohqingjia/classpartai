# ClassPart AI

IS469 Gen AI with LLMs group project (SMU, August Term 2026).

ClassPart AI assesses class participation (CP). A class recording becomes a reviewed transcript; a **coordinator agent** then works out, for every student, a provisional score per rubric criterion and individual feedback, checking claims against the course documents and auditing its own judgements. Nothing reaches a student until the professor approves the exact version.

It brings together **agentic RAG** (the evidence agent), **LLM-as-judge with an auditor** (evaluation), and an **agent harness with tools and guardrails** (budgets, schema-checked tools, approval-gated delivery).

The assessment workflow was designed and first built by Le Yong in TypeScript (`feat/assessment-foundation`) and ported to Python here; the Listener pipeline is Tina's (`audio-service/`).

## How it works

```
 class recording ──► ① LISTENER (Whisper → pyannote → SpeechBrain)
                         │  professor reviews attribution; unknown speakers stay "uncertain"
                         ▼
                   reviewed transcript + roster + rubric + course documents
                         │
                   COORDINATOR AGENT ── picks its next action from tool results, not a fixed order
                    ├─ inspect_transcript_context   look at turns before searching
                    ├─ retrieve_evidence ─────────► ② RESEARCH AGENT (agentic RAG)
                    │                                 pair question + answer → course notes or web →
                    │                                 grade → rewrite → verdict: correct? answers it?
                    │                                 reasoned? guess or misconception?
                    ├─ propose_rubric_assessment ─► ③ JUDGE (an agent): gets the rubric, each student's own
                    │                                 turns and the evidence summary in one message, scores every
                    │                                 student × criterion with a confidence, flags what needs the
                    │                                 professor (a revision re-scores only the audited students),
                    │                                 or says "insufficient evidence" (never counted as zero)
                    ├─ audit_assessment ──────────► ④ AUDITOR: deterministic checks + Auditor agent
                    │                                 (raise issues, one re-judge, or escalate)
                    ├─ draft_student_feedback ────► ⑤ FEEDBACK: strengths, next step, limitations
                    └─ request_professor_review     only when every student is covered and audited
                         │
                   ⑥ PROFESSOR: edit (new version) → approve the exact version → send via AgentMail
```

Every tool call and role output is schema-checked; a refused call goes back to the agent with the reason so it can choose again. One shared budget (model calls, tool calls, tokens, time) covers the coordinator and everything it invokes.

### Workflow vs agentic

| Part | Fixed workflow (code) | Agentic (the model decides) |
|---|---|---|
| Listener | transcribe → diarise → identify | — (the professor resolves uncertain speakers) |
| Coordinator | budget, tool validation, refusal of unsafe actions | which tool next, when to retrieve more, revise, or finish |
| Research agent (②) | session index, budgets, retry limits, verbatim-quote and exact-excerpt checks | course notes or web, queries and rewrites, which passages to grade, the answer's claims and expected points |
| Judge | every score is checked by `validate_proposal` (ranges, attribution, silence); budget; no approval or delivery tools | which tool next (rubric, evidence, a student's turns), the scores, confidence, justifications, what to flag |
| Auditor / Feedback | validation rules (privacy, coverage) | audit issues, feedback wording |
| Approval & delivery | everything: digest-matched approval, per-student delivery states | nothing; no model can approve or send |

## Guardrails (enforced in code)

- **Scores need evidence:** a score must cite the student's own turns and sit inside the rubric range; uncertain or professor turns can't establish a score; "insufficient evidence" is never zero; totals only when every criterion is scored.
- **Silence isn't failure:** no observed contribution can't support a qualitative score, and that student's feedback must say "No observed contribution" without inferring understanding.
- **Citations are real:** evidence citations must be exact excerpts of passages the agent actually retrieved in this session.
- **Privacy:** a student's feedback may not name another student.
- **Audit:** missing findings or feedback are blocking; trait claims ("lazy", "poor understanding") are flagged; the model auditor can raise issues but never lower scores.
- **Approval:** only the latest exact version; unresolved issues need an acknowledgement and reason; any edit or recipient change invalidates approval (SHA-256 digest of content + recipients).
- **Delivery:** recipients come from the roster, never a model; one delivery per student per version; accepted emails are never resent; ambiguous outcomes are never retried automatically; test mode redirects everything to one inbox.
- **Untrusted text:** transcript, documents and model output are always passed as data, never instructions.

## Agent workspace

Each session has seven inspectable agent tabs inside **AI assessment**, with exact inputs,
tool trajectories, outputs and guardrails. See [the workspace guide](docs/AGENT-WORKSPACE.md)
for the data sources, course-topic mapping and diagnostics recorded by new runs.

## Evaluation

| Part | What we measure |
|---|---|
| ① Listener | word error rate; speaker-attribution accuracy |
| ② Research agent | single-pass vs agentic RAG on 20 labelled IS469 Q&A pairs (`eval/research_eval.py`): routing, correctness, answers-the-question, context precision, cost. Results: [eval/results/research-is469-library.md](eval/results/research-is469-library.md) |
| ③ Judge | output: agreement with human scores on 20 hand-scored contributions (Spearman, quadratic-weighted Cohen's kappa; `eval/judge_eval.py`). Trajectory: finished, rules passed first try, scoring calls needed, flagged the injection, calls and cost |
| ④ Auditor | judge alone vs judge + auditor: issues caught, injected instructions flagged |
| Coordinator / harness | tool-call validity, refusals recovered from, budget use; unsafe actions blocked |

Plus latency, tokens and cost per session, and qualitative review of the drafts.

## Scope for the project

- **Input:** pre-recorded mock class clips, or the sample/fixture sessions in `data/`.
- **Speaker ID:** each team member records a 30-second voice sample.
- **Email:** AgentMail in test mode (one inbox).
- **Model:** OpenAI by default; any OpenAI-compatible endpoint via `OPENAI_BASE_URL` (e.g. a local model).

## Project layout

```
src/classpartai/
  assessment.py         session inputs: roster, reviewed transcript, rubric, documents (+ validation)
  evidence.py           evidence agent: course search index, citation checks, investigation loop
  research/             ② Research: agentic RAG over the IS469 files (and web) that also judges the
                        answer; bridge.py makes it the coordinator's evidence agent (default)
  llm.py                Research's chat/embedding wrappers (OpenAI or Ollama)
  models.py             OpenAI-compatible driver, tool schemas, shared budget
  participation/
    schema.py           findings, feedback, audits, drafts
    validation.py       the rules every draft must pass; totals; deterministic audit
    judge.py            the Judge agent: tools (evidence, contributions, score) and revisions
    roles.py            auditor (single call) and feedback roles
    auditor_bridge.py   runs Le Yong's Auditor agent (auditor_agent/) as the audit step;
                        AUDITOR=model explicitly selects the single-call role; agent errors
                        stay incomplete and require professor review (no automatic fallback)
    coordinator.py      the coordinator agent
    records.py          SQLite: sessions, evidence runs, versioned drafts, recipients, approvals
    delivery.py         approval-gated sending through AgentMail
  agents/listener.py    adapter from audio-service/ to a transcript
  classlist.py          names and emails, keyed by student ID
  library.py            course library: uploaded slides/readings/labs as session documents
  retrieval.py          what an evidence run searched and retrieved (for the vault view)
  usage.py              usage ledger: every model call's tokens, latency and estimated cost, plus trace
                        steps, kept in SQLite (events table)
  monitoring_ui.py      the Monitoring page: usage dashboard and per-run traces
  ui.py                 the animated workflow strip, student cards and the vault constellation
  assets/vault.html     the vault constellation page (canvas animation)
audio-service/          Listener pipeline: Whisper, pyannote, SpeechBrain (Tina)
app.py                  Streamlit app: Home checklist, Course library, Class & voices, and a five-step
                        session (record → who spoke? → AI assessment → approve → send)
data/                   sample IS469 session, Le Yong's fictional fixture, rubric, course notes;
                        is469/ Research's schedule and labelled Q&A (lecture files: data/raw/, git-ignored)
eval/                   research_eval.py: single-pass vs agentic RAG
tests/                  pytest (scripted fake models; no API calls)
deploy/                 Docker deploy for the VPS
```

## Using the app

1. **📚 Course library**: upload the slides, readings and labs the evidence agents may quote.
2. **👥 Class & voices**: add everyone with their email and role (student or professor), and
   record a voice sample for each (read the paragraph shown, about 20 s). Recording a seminar is
   locked until the professor and at least one student have a sample: the Listener can only name
   people it has heard, and speakers it can't name are never scored. Samples are stored on the
   server only (`audio-service/enrollments`, git-ignored), never in the repo.
3. **🎙️ New class session**: ① record or upload the seminar → ② check who spoke (play any line
   with ▶) → ③ run the agents → ④ approve → ⑤ preview and send the emails. Recordings are kept
   on the server for playback (`DATA_DIR/recordings`). The step bar names the agents at work in
   each step; every step is clickable, and the browser's back button walks back through them.
   To present without running the agents live, ③ **▶ Replay this run** plays a stored run's
   events again (one per click, or at 1×/5×/20× of its real timing) with no AI calls.
4. **📈 Monitoring**: what the agents used and did. A dashboard of model calls, tokens (cached and
   reasoning), estimated cost and latency by agent, model and day, and a trace of every step of each
   assessment run. It is kept in the app's database (`assessments.db`), so it survives restarts and
   redeploys. Costs come from `data/model_prices.json` (edit it to match your plan; a model with no
   price shows "no price", never $0); the OpenAI usage page is the source of truth for the bill.
   Each run's trace is also on the Coordinator tab of its Agent workspace.
5. **🧭 How it works**: the whole system on one page (pipeline diagram, why it's agentic,
   guardrails, IS469 topic map), for presenting.

No recording to hand? **▶ Use the demo recording** processes `data/demo_audio/seminar.ogg`, a
48-second mock seminar read by synthetic macOS voices, after enrolling those voices (marked as
demo voices; remove them on Class & voices). Regenerate it with `python scripts/make_demo_audio.py`.

Without access to the gated pyannote diarisation model, the Listener falls back to matching each
transcribed sentence against the enrolled voices (`agents/listener.py`): the best match must
score at least 0.35 and lead the runner-up by 0.10, otherwise the line stays unknown.

## Setup

Prerequisite: [uv](https://docs.astral.sh/uv/) (`brew install uv`, or `curl -LsSf https://astral.sh/uv/install.sh | sh`). uv installs the right Python version for you.

```bash
gh repo clone kohqingjia/classpartai
cd classpartai
uv sync                  # creates .venv and installs everything from uv.lock
cp .env.example .env     # then fill in the keys you need (see comments in the file)
```

## Running

```bash
uv run streamlit run app.py      # demo at http://localhost:8501
uv run jupyter lab               # notebooks (add jupyter first: uv add --dev jupyterlab)
```

### ③ Judge agent

The Judge is an agent (`participation/judge.py`), so it is evaluated on what it produced and how it got there. It needs `OPENAI_API_KEY` in `.env`; the human scores in `data/is469/judge_labels.jsonl` are drafts until the team marks them `reviewed`.

```bash
uv run python eval/judge_eval.py                  # agreement with human scores, plus trajectory metrics
uv run python eval/judge_eval.py --evidence none  # the Judge without Research's findings
```

### ② Research agent

Needs `OPENAI_API_KEY` in `.env`, or `LLM_PROVIDER="ollama"` to run free on a local model (setup
in `.env.example`); `TAVILY_API_KEY` adds the web source. Its course data is IS469:
copy the Topic 1–8 decks and labs into `data/raw/is469/` (git-ignored; see `data/README.md`).

```bash
uv run python -m classpartai.research check        # are the models, lecture files and index ready?
uv run python -m classpartai.research ingest       # embed the decks and labs (rerun when they change)
uv run python -m classpartai.research run "LoRA only trains two small matrices." \
    --question "Why does LoRA fit on one GPU when full fine-tuning does not?" \
    --date 2026-09-08 --trajectory                 # one answer: verdicts, quotes, every tool call
uv run python eval/research_eval.py                # single-pass vs agentic RAG on labelled Q&A pairs
uv run python eval/research_eval.py --documents var/library/documents.json --max-usd 1
                                                   # the same on the app's course library, with a
                                                   # spending cap; writes eval/results/*.{md,json}
```

Research takes a professor's question and a student's answer from the transcript, and works out two
things with evidence from the course materials (or the web):

- **Is the answer correct?** Each of the student's claims gets a verdict (`supported`,
  `contradicted`, `mixed`, `partially_supported`, `unverified`), combined into `correctness`:
  `correct`, `partially_correct`, `incorrect` or `unverified`.
- **Does it answer the question?** Research finds what the course says a good answer contains
  (`expected_points`), and reports `answers_question` (`yes`, `partly`, `no`) and the
  `missed_points`. A true statement about something else is correct but does not answer it.

- **How good is the attempt?** `reasoning` (`explained`, `asserted`, `none`) and, when the answer is
  wrong, `mistake` (`reasonable_guess`, `misconception`, `unsupported`), so the Judge can give
  credit for an educated guess. Research reports these signals; the Judge decides the marks.

Every verdict comes from graded evidence with verbatim quotes and sources (deck and slide, lab and
cell, or URL). On its own (the commands above), Research searches the IS469 index and the web. In
code, call
`ResearchAgent.from_config().research_contribution({"id", "student", "question", "text"}, date)`
and passes the returned `EvidencePack` (`.brief()` for a prompt) to the Judge, which does the
scoring. Without a `question` it treats the text as an unprompted comment. The Judge's follow-up
questions (J1) go to `answer_question(question, date)`.

#### Inside the assessment workflow

`research/bridge.py` makes Research the workflow's evidence agent without changing any contract:

| Link | What it does |
|---|---|
| ① Listener → ② | `answer_pairs(transcript)` pairs each student's answer with the professor question before it (uncertain speakers are skipped) |
| ② → coordinator | `retrieve_evidence` (and the app's *Investigate* button) runs Research and returns the same `EvidenceBundle` as `evidence.py` (set `EVIDENCE_AGENT="course"` to use that agent instead): exact excerpts of the session's passages as citations, conflicts and gaps |
| ② → ③ Judge | the bundle's `explanation` carries the answer assessment (correctness, answers the question, reasoning, kind of mistake, missed points); the full `EvidencePack` is saved with the evidence run |
| Course or web | Research still decides per answer: the session's course documents, or the web (with `TAVILY_API_KEY`; `RESEARCH_BRIDGE_WEB=false` turns it off). Only course passages become citations, which the validator requires; web findings reach the Judge as labelled context with their links |
| Budget | every Research model and tool call counts against the workflow's shared budget; inside a session Research uses lighter budgets (`RESEARCH_BRIDGE_*`) |
| IS469 files → sessions | `export-documents` turns the lecture files into session documents, so either evidence agent can search the real slides instead of the demo notes |

```bash
uv run python -m classpartai.research export-documents   # writes var/is469_documents.json (git-ignored)
# then in .env: COURSE_DOCUMENTS="var/is469_documents.json"  (sessions made from new recordings)
uv run python -m classpartai.research session data/sample_assessment.json --date 2026-10-20
                                                          # research every answer in a session file
```

## Checks

Run these before every push; CI runs the same three.

```bash
uv run ruff check .              # lint (add --fix to auto-fix)
uv run ruff format .             # format
uv run pytest                    # tests
```

## Reproducibility

All randomness goes through `classpartai.config.set_seed()` (seed from `SEED` in `.env`, default 42). Dependencies are pinned in `uv.lock`; add new ones with `uv add <package>` so the lockfile stays in sync.

## Contributing

See [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md). New teammates start with [docs/TEAMMATE-SETUP.md](docs/TEAMMATE-SETUP.md).
