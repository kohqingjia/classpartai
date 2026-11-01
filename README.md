# ClassPart AI

IS469 Gen AI with LLMs group project (SMU, August Term 2026).

ClassPart AI grades class participation (CP). It listens to a class recording, works out who said what, checks each contribution against the course materials (or the web), scores it against a CP rubric with an LLM judge, has a second agent audit those scores, and decides who should hear about the results. The professor approves anything before it reaches a student.

It brings together three course topics: **agentic RAG**, **LLM evaluation (LLM-as-judge)**, and an **agent harness with tools and guardrails**.

## How it works

Five agents, run in order. A fixed pipeline handles the steps that never change; the agents take over where a decision is needed.

```
 class audio
     │
 ① LISTENER ── transcribe → diarise → identify speaker → triage
     │   L1 speaker match uncertain? → look for name cues / compare voices / re-transcribe / flag
     │   L2 substantive? ("can you repeat that" → count only, don't score)
     ▼
 contributions [{student, text, timestamp}]
     │
 ② RESEARCH (agentic RAG)
     │   R1 route → course slides/readings | web | none (opinion, logistics)
     │   R2 evidence weak? → rewrite query, retry (max 2) → switch source → else "unverified"
     ▼
 ③ JUDGE ── rubric + contribution + evidence → per-criterion scores + rationale
     │   J1 evidence doesn't cover a claim? → ask Research for more
     │   J2 which criteria apply? (question / answer / building on / challenge)
     ▼
 ④ AUDITOR ── challenges the Judge before anything is acted on
     │   A1 consistent with similar contributions?   A2 rationale matches evidence?
     │   A3 instructions aimed at the grader?         A4 bias (length, loudness, ASR quality)?
     │   A5 verdict → approve | send back to Judge (one round max) | escalate to prof
     ▼
 ⑤ ACTION (harness) ── decides who gets told what
     │   • every session → summary email to the prof
     │   • flagged items  → prof review queue
     │   • student feedback → drafted, sent only after the prof approves
     ▼
 scores saved, emails sent
```

### Workflow vs agentic

| Agent | Fixed workflow part | Agentic part (the LLM decides) |
|---|---|---|
| ① Listener | transcribe → diarise → identify | how to resolve an uncertain speaker; whether a turn is substantive |
| ② Research | — | which source, whether evidence is good enough, rewrite / retry / switch |
| ③ Judge | — | whether to request more evidence; which criteria apply; whether to check history |
| ④ Auditor | — | which checks to run; approve, send back or escalate |
| ⑤ Action | permission checks (enforced in code) | who to notify, tone, batch vs flag, follow-up suggestions |

The agent proposes, the harness disposes: tools like `send_email` enforce the rules in code, so an agent cannot email a student without the prof's approval, whatever it decides.

## Agent tools

Plain Python functions the agents call. Signatures are a starting point.

### ① Listener

| Tool | Returns |
|---|---|
| `transcribe_audio(audio_path)` | segments with text and timestamps (Whisper) |
| `diarize_speakers(audio_path)` | speaker turns (`SPK_1` from 0:12 to 0:40) |
| `identify_speaker(turn_audio)` | `student_id` and confidence, matched against enrolled voice samples |
| `get_roster(class_id)` | students and their enrolled voice samples |
| `find_name_mentions(transcript, around)` | names spoken near a timestamp ("good point, Sarah") |
| `compare_to_speaker(turn, student_id)` | similarity to that student's other turns |
| `retranscribe(segment, model)` | a fresh transcription of a garbled segment |

### ② Research

| Tool | Returns |
|---|---|
| `get_lesson_context(date)` | that week's topic, so the agent knows what is on-topic |
| `search_course_materials(query, week=None, k=5)` | chunks and sources (deck, page) from a vector store of slides and readings |
| `search_web(query, k=5)` | snippets and URLs |
| `grade_evidence(claim, chunks)` | relevant / partial / irrelevant, and whether it supports or contradicts the claim |

### ③ Judge

| Tool | Returns |
|---|---|
| `get_rubric(course_id)` | criteria with level descriptors (relevance, accuracy, depth, building on others) |
| `classify_contribution(text)` | question / answer / building on / challenge |
| `request_research(question)` | calls the Research agent for more evidence |
| `score_contribution(text, evidence, rubric)` | per-criterion scores, a rationale citing evidence, and confidence |
| `get_student_history(student_id)` | past scores, for trends and fairness |

### ④ Auditor

| Tool | Returns |
|---|---|
| `get_session_scores(session_id)` | every score and rationale from the class |
| `compare_similar(contribution_id, k=3)` | the most similar contributions and their scores (embedding similarity) |
| `verify_citation(rationale, evidence)` | whether each claim in the rationale is supported by the cited evidence |
| `detect_injection(text)` | whether the text contains instructions aimed at the grader |
| `score_stats(session_id)` | score against speaking time and ASR confidence, to spot bias |
| `request_rejudge(contribution_id, reason)` | sends a contribution back to the Judge with the objection |

### ⑤ Action

The agent's tools (`src/classpartai/action/agent.py`). Every effect goes through the harness (`action/harness.py`), which enforces the rules in code.

| Tool | Does |
|---|---|
| `list_students()` | everyone on the class list with this session's participation, plus unidentified speakers |
| `get_student_contributions(person_id)` | that student's contributions, scores and audit (transcript marked as student data) |
| `get_student_history(person_id)` | their earlier sessions |
| `draft_student_email(person_id, kind, subject, body)` | a `commend` / `encourage` draft, **pending** until the prof approves it in the webapp |
| `flag_for_review(reason, person_id?, contribution_id?)` | adds to the prof's review list |
| `send_prof_summary(subject, body)` | the one email sent without separate approval |

Harness rules: student emails only after approval in the **Feedback emails** tab; recipients only from the class list; unidentified speakers never emailed; no other student named in an email (re-checked after the prof edits); one email per student, kind and session; a daily cap; test mode (on by default) redirects everything to one inbox. Sent through AgentMail with an idempotency key.

## Evaluation

Each comparison pits two alternatives against each other, as the brief requires.

| Agent | What we measure |
|---|---|
| ① Listener | word error rate; speaker-attribution accuracy |
| ② Research | single-pass RAG vs agentic RAG: faithfulness, context precision |
| ③ Judge | agreement with human scores on ~30 hand-scored contributions (Spearman, Cohen's kappa); with vs without evidence |
| ④ Auditor | Judge alone vs Judge + Auditor: consistency, injections caught, human agreement |
| ⑤ Action | tool-call correctness; unapproved student emails blocked |

Plus latency and cost per session, and qualitative review of real outputs.

## Risks and guardrails

| Risk | Mitigation |
|---|---|
| Wrong speaker credited | L1 confidence threshold; flag rather than guess |
| Transcription worse on some accents | prof sees the transcript in review; score content, not fluency; Auditor bias check (A4) |
| Prompt injection by voice or web page ("give me full marks") | transcript and retrieved text treated as data in prompts; `detect_injection`; adversarial test set |
| Judge hallucinates or is too harsh | rationale must cite evidence; Auditor verifies citations (A2); extreme scores go to review |
| Recording students (consent, PDPA) | mock recordings for the project; consent required for real use |

## Scope for the project

- **Input:** pre-recorded mock class clips, not live audio.
- **Speaker ID:** each team member records a 30-second voice sample.
- **Email:** test inboxes only.
- **Demo:** a Streamlit page to upload audio, see the transcript and scores, and approve or reject emails.

## Project layout

```
src/classpartai/
  contracts.py        the data each stage hands to the next (agree changes with both neighbours)
  orchestrator.py     runs Research -> Judge -> Auditor over a session
  agents/
    listener.py       ① adapter over audio-service/ (Tina)
    research.py       ② PLACEHOLDER: returns no evidence
    judge.py          ③ PLACEHOLDER: neutral 3/5 on every criterion
    auditor.py        ④ PLACEHOLDER: approves everything
  action/             ⑤ Action agent (LLM + tools) and the harness that enforces the rules
  classlist.py        names and emails, keyed by person_id
  config.py           paths, env vars, seed
audio-service/        Listener pipeline: Whisper, pyannote, SpeechBrain
app.py                Streamlit demo: Analyse / Feedback emails / Class list
data/                 sample session + class list for demoing without audio
eval/  notebooks/     evaluation scripts and experiments
tests/                pytest
deploy/               Docker deploy for the VPS
```

### Building your stage

Each stage is one function in `src/classpartai/agents/`. Replace the placeholder body, keep the signature and return type from `contracts.py`, and set `IS_PLACEHOLDER = False`. The app labels results as "not real" until every stage is built.

| Stage | Function | Returns |
|---|---|---|
| ① Listener | `to_contributions(result, session_id, ids_by_name)` | `list[Contribution]` |
| ② Research | `research(contribution, topic)` | `Research` |
| ③ Judge | `judge(contribution, research)` | `Judgement` |
| ④ Auditor | `audit(contribution, judgement)` | `Audit` |
| ⑤ Action | `ActionAgent(harness).run(session)` | drafts, flags, prof summary |

`data/sample_session.json` is a complete `SessionResults` you can test against without running the stages before yours.

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
