# Agent workspace

Open a session's **AI assessment** step. Overview comes first; its pipeline links activate the
seven native Streamlit tabs. The session keeps Record → Who spoke? → AI assessment → Approve →
Send. Home, Course library and Class & voices remain accessible from the sidebar.

The default view is designed for a presentation: a purpose/status header, a simple handoff,
and the current result. **Inspect details** opens the complete trace without mixing it into the
presentation. Overview keeps live activity in plain language, and Approve/Send lead with the
current version and approval state. Nothing is simulated when a result is unavailable.

Every agent inspector has a status/topic header, Inputs, Tools it may call, Trajectory / timeline,
Outputs, and Guardrails that fired. Inspectors read persisted results; they do not run models or
validate a draft again. Approval and delivery still use the existing backend gates.

| Tab | Recorded source | IS469 topic |
| --- | --- | --- |
| Listener | `records.inputs`, `records.listener_run`, `DATA_DIR/recordings/<session_id>.wav`, `voices.enrolments` | Preprocessing; Topic 2 encoder-decoder transformers; Topics 1/8 embeddings + cosine |
| Coordinator | `records.runs().progress`: actions, initial input, shared usage, elapsed seconds | Topic 7 Agents, tool calling, harness |
| Evidence / Research | `records.evidence_runs().progress`: searches, research packs, trajectory, bundle; pinned documents | Topic 8 Agentic RAG: BM25 + vectors + RRF, corrective retrieval |
| Judge | `progress.roleCalls` (one entry per tool call the Judge made, role `judge_agent`), `draft.content.findings` with confidence and flags, transcript and evidence citations | Topic 6 Evaluation: rubric LLM-as-judge; Topic 7 Agents |
| Auditor | `progress.roleCalls`, `draft.content.audit.issues`, version history | Topic 6 Evaluation: verify first, judge last |
| Feedback writer | `progress.roleCalls`, needs-evidence outputs, `draft.content.feedback` | Topic 7 Agents; Topic 9 privacy |
| Delivery | Approvals, recipient revisions, deliveries, attempts; production `feedback_email` formatter | Topic 9 Ethics: exact-version human approval, test mode |

## Additional diagnostics

- Role calls record the exact instructions, schema, input data/history, structured response,
  correction attempt, validation outcome and refusal reason. They contain public structured
  results, never hidden reasoning. They remain outside model history and do not consume extra
  model/tool calls or change prompts, retry counts, limits or scoring.
- Coordinator actions retain requested arguments and the returned result, including refusals.
  Initial coordinator input and elapsed time are recorded alongside existing counters.
- Research retains public model history, exact tool returns and both refused and accepted
  submissions. Search hits preserve BM25, cosine and RRF scores plus the retrieved chunk text.
  Ranking and model-visible search results are unchanged.
- New recordings retain their WAV and raw Whisper/alignment/verification diagnostics, in an
  additive `listener_runs` table. Reviewed assessment inputs remain separate and unchanged.
- Older runs and imported/demo transcripts explicitly report missing diagnostics. No scores,
  role calls, recordings or trajectories are fabricated to fill a view.

### Listener decision rule

This branch's speaker identifier uses SpeechBrain's `same_speaker` accepted-match flags:
zero accepted matches means UNKNOWN, multiple means AMBIGUOUS. It does **not** implement an
explicit threshold of 0.35 plus a best/runner-up margin of 0.10. The inspector shows these requested
reference values beside recorded cosines, labels their diagnostic-only meaning, and preserves the
existing rule. Changing the rule would require a separate, behaviour-changing task.

## Rendering and verification

Self-contained iframe visuals use escaped JSON and `textContent`; no untrusted HTML or external
CDNs. The constellation advances only on user input. Native Streamlit elements carry live counters
and event details, so two-second refreshes do not change iframe HTML just to update a clock.
All transition effects use opacity/transform and respect reduced motion.

`tests/test_agent_ui.py` opens every outer page, every session step and every agent tab in presentation and inspection modes, in empty and
populated states. It exercises acknowledgement, approval, test-mode redirect and accepted-send
idempotency with a fake transport. Other tests verify exact role traces, correction histories,
unchanged call counts, retrieval diagnostics, safe iframe JSON and Listener score preservation.

Run the standard checks before pushing:

```sh
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

The browser walkthrough uses the committed demo transcript without live AI/email credentials.
The walkthrough covers Home → Class & voices → New class session → Skip to the demo transcript →
AI assessment (all seven agent tabs and inspection) → Approve → Send. The pipeline links were
clicked, and layouts checked at 1280, 1440, 1600 and 390 px. No real email was sent.

Screenshots under `docs/screenshots/` show the included demo transcript and the existing
**Write it myself** unassessed professor template. Its origin is labelled, its findings remain
insufficient evidence, and its audit explicitly says the model audit is pending. No model result,
voice diagnostic or citation was fabricated for these screenshots. Scripted test drivers exercise
populated AI traces and delivery through a fake transport.
