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
                    ├─ retrieve_evidence ─────────► ② EVIDENCE AGENT (agentic RAG)
                    │                                 search → reformulate → fetch → cite exact excerpts
                    ├─ propose_rubric_assessment ─► ③ JUDGE: one finding per student × criterion,
                    │                                 or "insufficient evidence" (never counted as zero)
                    ├─ audit_assessment ──────────► ④ AUDITOR: deterministic checks + model review
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
| Evidence agent | scoped search index, exact-excerpt citation check | queries, reformulation, which passages to fetch, sufficient vs gap |
| Judge / Auditor / Feedback | validation rules (ranges, attribution, privacy) | scores and justifications, audit issues, feedback wording |
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

## Evaluation

| Part | What we measure |
|---|---|
| ① Listener | word error rate; speaker-attribution accuracy |
| ② Evidence agent | single-pass retrieval vs agentic (reformulate/fetch): citation validity, sufficient-vs-gap accuracy |
| ③ Judge | agreement with human scores on hand-scored sessions (Spearman, Cohen's kappa) |
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
  models.py             OpenAI-compatible driver, tool schemas, shared budget
  participation/
    schema.py           findings, feedback, audits, drafts
    validation.py       the rules every draft must pass; totals; deterministic audit
    roles.py            judge, auditor and feedback roles
    coordinator.py      the coordinator agent
    records.py          SQLite: sessions, evidence runs, versioned drafts, recipients, approvals
    delivery.py         approval-gated sending through AgentMail
  agents/listener.py    adapter from audio-service/ to a transcript
  classlist.py          names and emails, keyed by student ID
  ui.py                 the animated workflow strip and student cards
audio-service/          Listener pipeline: Whisper, pyannote, SpeechBrain (Tina)
app.py                  Streamlit app: Session / Evidence / Assessment / Approve & send / Class list
data/                   sample IS469 session, Le Yong's fictional fixture, rubric, course notes
tests/                  pytest (scripted fake models; no API calls)
deploy/                 Docker deploy for the VPS
```

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
