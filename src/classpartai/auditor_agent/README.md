# ClassPart AI Auditor

For your presentation, start with these **three files**:

| Main file | What to explain |
| --- | --- |
| **`agent.py`** | The **prompt** tells the Auditor its goal. The model connection asks the LLM for tool calls. `AuditorAgent.run()` starts an audit. |
| **`harness.py`** | The **harness** gives the model its tool menu, validates and executes calls, returns observations, handles recovery and enforces limits. Start at `run_audit()`. |
| **`tools.py`** | The **tools** implement the individual checks: comparison, citation verification, injection detection, statistics and rejudge handoff. |

```text
auditor_agent/
  agent.py             PRESENT: prompt and LLM connection
  harness.py           PRESENT: tool menu and controlled execution loop
  tools.py             PRESENT: actual audit checks
  contracts.py         Supporting input/output and state validation; required at runtime
  __init__.py          Public package imports
  __main__.py          Terminal entry point
  README.md
  examples/
    demo.py            Fictional demonstration
    evaluation.py      Controlled comparison experiments
    data/              Fictional JSON inputs/results
  tests/
    test_auditor.py     Automated checks
```

The presentation flow is `agent.py → harness.py → tools.py → observation back to the model`.
In `harness.py`, find `budget.choose(...)` (model chooses), `getattr(tools, ...)` (harness executes)
and `messages.extend(...)` (tool result becomes the next observation). The framework does not
mandate a sequence of all tools. The LLM chooses the next action while Python enforces the rules.
`contracts.py` remains necessary supporting validation; examples/tests are kept together so they
do not obscure the three main files.


A second marker for provisional, per-contribution rubric findings. It investigates the Judge's
rationales and evidence, then returns `audit_passed`, `rejudge_requested`, or
`professor_review_required`. It never calculates a replacement grade, approves grades, sends
email, invokes the Judge, or writes application records. Audit pass is not professor approval.
The workflow's `audit_assessment` step runs it through `participation/auditor_bridge.py`.
`AUDITOR=model` explicitly selects the single-call `roles.model_audit`; agent errors no longer
trigger an automatic fallback. See the integration behaviour below.

## Integrated workflow behaviour

The coordinator calls `persisted_agent_audit`, which reserves and saves the trusted Auditor
state in the application's SQLite `auditor_state` table. `CREATE TABLE IF NOT EXISTS` adds the
table on opening Records; existing session/draft tables and data are preserved. There is no new
dependency or external service. Restart the app normally with `uv run streamlit run app.py`.

- **Speaking time:** the union of each student's reviewed speaking intervals, excluding gaps
  and counting overlaps once. `score_stats` excludes no-observation records from duration
  correlations and reports sample size and exclusions. Old standalone single-interval fixtures still
  work and are labelled with a legacy interval count.
- **Answer comparisons:** original turn IDs and full reviewed turn text are retained, with no
  fabricated segments or silent input truncation. `compare_similar` returns up to three lexical
  answer pairs per candidate, with excerpt flags and a 10,000-pair limit/completeness indicator.
  Scores remain student aggregates because that is what the Judge produces; these are not
  invented per-answer grades. Lexical similarity is not semantic equivalence or equal quality.
- **Silent students:** included with `assessment_scope=no_observed_contribution`, empty turn
  lists and zero observed speaking time. Unknown qualitative scores stay unassessed. A numeric
  score requires an explicit `no_contribution_score` on the exact rubric criterion. No turn or
  understanding claim is invented. Unsupported mapping coverage is raised as a visible issue.
- **Bounded inputs:** the 150 KB request limit and finding/roster limits remain. Oversized input
  requires professor review instead of silently dropping text or falling back to a weaker audit.
- **Rejudge:** one allowance per assessment session, persisted across coordinator runs. Pending
  objections and issue-ID mappings survive reopening the database. Changed finding sets or
  broken lineage require review and never start a fresh allowance. After the round is used,
  subsequent audits remain possible but `request_rejudge` is removed from the model's menu and
  refused if fabricated. Only a valid linked revision can resolve the original objections.
- **Concurrency/interruption:** a SQLite write transaction reserves the session audit before
  execution; a versioned reservation guards state writes. Concurrent calls cannot claim it.
  A hard process crash leaves an interrupted reservation and requires professor review; there
  is no automatic timeout reset, durable resume, or UI for administratively releasing it.
  Normal handled failures release the reservation while retaining the trusted case state.
- **Failure visibility:** provider/mapping/reader failures return an explicit incomplete issue
  and `modelReviewed=false`; they do not invoke the single-call reviewer automatically. The
  coordinator may escalate; approval still requires the professor's explicit acknowledgement
  and reason for open issues. `AUDITOR=model` remains an explicit implementation choice.

The Auditor still cannot change scores, invoke the Judge, approve or send email. The coordinator
receives targeted objections and chooses whether to revise, investigate or escalate. Existing
records created before this table have no retroactively reconstructed rejudge history. The
standalone CLI remains stateless: its caller must persist and enforce its case state separately.

## Groq setup (no OpenAI key required)

Add these settings privately to the repository-root `.env`:

```text
AUDITOR_PROVIDER="groq"
GROQ_API_KEY="your-groq-api-key"
GROQ_MODEL="openai/gpt-oss-20b"
```

The model is configurable and must be available to your Groq account with tool calling. This
model is listed in the [Groq tool-use documentation](https://console.groq.com/docs/tool-use/overview).
No real API key is stored in the examples, and the actual `.env` was not edited during this change.

Run with the existing project environment:

```text
uv sync
uv run python -B -m classpartai.auditor_agent src/classpartai/auditor_agent/examples/data/example_request.json --evidence src/classpartai/auditor_agent/examples/data/example_evidence.json --provider groq
```

The explicit `--provider groq` is optional when `AUDITOR_PROVIDER=groq` is set. A successful live
run reports `execution_label: groq`. Leave out `--test-double` to use the real model. The inputs
above remain fictional Judge proposals; a live provider supplies the actual Auditor decisions.
The Action agent still uses its original OpenAI settings and is not changed by this selection.

Groq uses the existing OpenAI-compatible SDK with fixed endpoint
`https://api.groq.com/openai/v1`, documented in the
[Groq compatibility guide](https://console.groq.com/docs/openai). No Groq SDK or other dependency
was added. The adapter omits `store` for Groq because its
[Chat Completions reference](https://console.groq.com/docs/api-reference) marks that parameter
unsupported. Native tools, one-call-at-a-time execution, token/output caps, timeouts and disabled
SDK retries remain. A missing key, provider error or rate limit never triggers fallback to OpenAI.

Provider selection: explicit Python/CLI provider overrides process `AUDITOR_PROVIDER`, then
`.env`, then `openai`. The selected provider uses its own key/model variables only:

| Provider | Key | Model | Default model |
| --- | --- | --- | --- |
| `groq` | `GROQ_API_KEY` | `GROQ_MODEL` | `openai/gpt-oss-20b` |
| `openai` | `OPENAI_API_KEY` | `OPENAI_MODEL` | `gpt-5-mini` |
| `local` | None | `AUDITOR_MODEL` | No default |

Python callers can use `AuditorAgent(reader, provider="groq")`. The evaluation command with
`--live` also honours `AUDITOR_PROVIDER`; its offline mode always injects doubles.

Changes for Groq, all inside this folder:

- `agent.py`: explicit provider selection, Groq endpoint/key/model, provider-specific request
  options; existing OpenAI and local paths retained.
- `__main__.py`: `--provider` option and correct `groq` execution label.
- `harness.py`: missing-configuration message mentions both hosted key variables.
- `examples/evaluation.py`: provider-neutral help and blocked-state wording.
- `tests/test_auditor.py`: six offline Groq checks for credentials/endpoint, request compatibility,
  precedence, no fallback, nested audit calls and CLI labelling.
- `README.md`: setup commands, configuration reference and this change record.

Verification: all **46 tests passed** on Python 3.12, using fictional SDK doubles and a local
HTTP protocol double. The initial Groq adapter verification used test doubles. The subsequent live diagnosis and
its limitations are recorded below; no complete live assessment pass has yet been verified.

## Shared OpenAI configuration

The Auditor now uses the **same root `.env` variables as `action/agent.py`**:

```text
OPENAI_API_KEY="your-existing-key"
OPENAI_MODEL="your-selected-model"
```

There is no separate Auditor API key. Do not duplicate or commit your real key. `OPENAI_MODEL`
is optional; the default is `gpt-5-mini`, matching the Action agent. Model availability/account
access must be verified separately. Your previous free-only restriction was explicitly lifted;
running an OpenAI-selected Auditor makes OpenAI requests, including citation-review calls.
With `AUDITOR_PROVIDER=groq`, the Groq configuration above is used instead.

The project already declares `openai>=1.60` in its root dependencies. Use the existing setup:

```text
uv sync
```

No dependencies, lockfiles or files outside this folder were changed for this adapter. No model
SDK is imported during offline tests unless a test deliberately supplies a fake SDK module.

Configuration precedence is explicit model/client override, process environment, root `.env`,
then the model default. An empty process `OPENAI_API_KEY` overrides the file and leaves the
Auditor blocked. Settings are loaded at agent construction, not module import. Reconstruct the
agent after changes. The small dependency-free loader reads single-line assignments for the selected provider settings; it supports optional `export`, quotes and comments. It does
not expand variables, execute commands, log values, mutate `os.environ`, or import root modules.
Missing key means a configuration-blocked result; missing SDK means setup must run `uv sync`.
Provider errors never produce a pass or trigger automatic local/provider fallback.

## Python entry points

Like `ActionAgent(harness).run(session)`:

```python
from classpartai.auditor_agent import AuditorAgent

agent = AuditorAgent(evidence_reader=your_authorised_reader)
result = agent.run(request_dict)
result_dict = result.to_dict()
```

The lower-level, explicitly injected entry point is preserved:

```python
from classpartai.auditor_agent import audit_proposal

result = audit_proposal(request_dict, model=your_model, evidence_reader=your_reader)
```

`AuditorAgent(reader, client=your_openai_client, model_name="your-model")` accepts an SDK client
like the Action agent. `AuditorAgent(reader, model=your_model_adapter)` bypasses environment
loading and SDK creation entirely. Offline demos always inject a labelled fictional double.

The OpenAI adapter uses native function calling through `client.chat.completions.create`.
It requires one tool call, disables parallel calls and SDK automatic retries, applies the shared
remaining timeout, caps completion tokens at 4,000 for OpenAI (2,048 for Groq), and sets `store=False` for OpenAI. Prose-only responses
or malformed arguments are refused. Tool permissions and validation stay in the harness.
See the [official function-calling guide](https://developers.openai.com/api/docs/guides/function-calling).

## Run from the repository root

Fictional offline demo and tests (no API calls):

```text
uv run python -B -m classpartai.auditor_agent.examples.demo
uv run python -B -m unittest classpartai.auditor_agent.tests.test_auditor -v
uv run python -B -m classpartai.auditor_agent src/classpartai/auditor_agent/examples/data/example_request.json --evidence src/classpartai/auditor_agent/examples/data/example_evidence.json --test-double
```

Real OpenAI execution using the shared key/model:

```text
uv run python -B -m classpartai.auditor_agent src/classpartai/auditor_agent/examples/data/example_request.json --evidence src/classpartai/auditor_agent/examples/data/example_evidence.json
```

An optional `--model MODEL_NAME` overrides `OPENAI_MODEL` for one CLI run. Without uv, a Python
3.12+ interpreter can run the same modules with `PYTHONPATH=src`; OpenAI mode still requires the
project's declared SDK dependency in that interpreter's environment.

The CLI accepts `-` for JSON stdin. It emits JSON with an `execution_label` of `groq`, `openai`,
`local_model`, `fictional_test_double`, or `configuration_blocked` alongside the `AuditResult`
fields. Remove that presentation label before strict `AuditResult.parse()` round trips.
Exit 0 means a structured result, not necessarily a pass; exit 2 means invalid configuration/input.
No secrets or provider error bodies are printed.

## File guide

| File | Responsibility |
| --- | --- |
| `agent.py` | `PROMPT`, `SCORE_PROMPT`, `AuditorAgent`, shared configuration, and model connections. |
| `tools.py` | Scoped audit tools, source/quote validation, semantic support review and deterministic guardrails. |
| `harness.py` | Tool definitions, observe/choose/validate/execute loop, working memory, recovery and shared budgets. |
| `contracts.py` | Versioned dataclasses and runtime JSON validators for inputs, state, handoffs and results. |
| `examples/demo.py` | Fictional Judge, in-memory evidence reader and explicitly deterministic model double. |
| `tests/test_auditor.py` | Offline protocol, guardrail, configuration and lifecycle tests. |
| `examples/evaluation.py` | Controlled one-change-at-a-time comparisons, fictional fixtures and an explicit live evaluation option. |
| `__init__.py`, `__main__.py` | Public imports and CLI entry point. |

The former `model.py` was renamed to `harness.py`, and the actual execution loop moved there
from `agent.py`. Prompt constants are now `PROMPT` and `SCORE_PROMPT`. All executable code is Python.

## Contracts and field ownership

`contracts.py` is the authoritative schema-v1 contract. Unknown fields, non-finite scores,
booleans as scores, duplicate IDs, invalid ranges/references and bad lineage are rejected.

| Contract / fields | Supplier and meaning |
| --- | --- |
| `AuditRequest.schema_version`, `audit_case_id` | Orchestrator: v1 and stable case ID reused for a revision. |
| `trusted_scope.course_id`, `session_id` | Authenticated caller/backend, not model arguments or imported text. |
| `rubric` | Professor-authorised exact ID/version, criterion IDs, descriptors and ranges. |
| `contributions` | Reviewed text, contribution/turn IDs, start/end milliseconds and attribution. Transcription confidence is not used. |
| `student_id`, `attribution` | Reviewed identity: identified requires an ID; uncertain/unknown require null. No silent reassignment. |
| `JudgeProposal` | Judge: versioned reference, previous proposal and rejudge-request links, exact rubric version and findings. |
| `Finding` | Stable finding/contribution/criterion IDs, nullable provisional score, rationale, transcript references and citations. These are per contribution, not student aggregates. |
| `EvidenceRef` | Research/Judge: evidence/source/version/passage IDs, page and exact quotation. |
| `AuditState` | Trusted caller-owned state, round count, previous reference, pending objections, immutable-input fingerprint and finding bindings. |
| `Issue` | Auditor: kind, severity, affected findings, evidence IDs and concise objection; never a replacement score. |
| `RejudgeRequest` | Auditor: case ID, original proposal, request ID, affected criteria/findings, specific objections and evidence references. |
| `AuditResult` | Auditor: audited reference, verdict, issues, affected findings, evidence IDs, trace, usage, stop reason and updated state. |

Examples under `examples/data/` are fictional: `example_request.json`, `example_evidence.json`,
`example_rejudge_request.json`, `example_revised_request.json`, and `example_output.json`.
Output examples are from test doubles, not live model assessments or human scoring labels.
Null scores are unassessed, never silently zero. Uncertain attribution forces professor review.
The caller must supply the intended finding coverage; this component cannot discover omitted
roster students or upstream contributions.

## Model-selected route and tools

The harness repeatedly asks the model to choose a typed tool, validates its arguments, executes
it, and returns the result into per-run working memory. It does not mandate all tools or a fixed
order. Inspecting required findings and citations before passing is a safety invariant.

| Tool | Behaviour |
| --- | --- |
| `get_session_scores(offset, limit)` | Read at most ten scoped findings/rationales per page. |
| `compare_similar(finding_id, k)` | Same rubric criterion; up to five lexical token-Jaccard comparisons, not embeddings. Similar wording does not justify equal scores. |
| `verify_citation(finding_id, evidence_id)` | Validate scoped source/version/page IDs and exact quote, then use a nested model call for supports/partly_supports/contradicts/fails_to_verify. Semantic support is model interpretation, not certainty. |
| `detect_injection(target, target_id)` | Inspect original scoped text; distinguish suspected grader instructions and narrowly framed benign quoted examples. Heuristic, not an immunity guarantee. Original text remains unchanged. |
| `score_stats()` | Descriptive speaking-duration correlations, sample sizes and exclusions. No loudness inference or claim of proven bias. |
| `request_rejudge(issues)` | Validate targeted findings/evidence and create a handoff once; never call the Judge. |
| `complete_audit(...)` | Propose pass/escalation; backend refuses unearned passes and unknown issue resolutions. |

Transcripts, rationales, retrieved material and tool results are untrusted data. Allowlisted
tools, strict argument schemas, closure-bound scope, quotation checks and verdict validation
remain outside model control. Discovered guardrail issues cannot be silently erased by a model.

Default shared budget: 16 total model calls (including nested citation reviewers), 12 outer tool
steps, 30 seconds. Maximum configurable limits: 40 calls, 30 steps, 120 seconds. Working memory,
request/response sizes and completion length are bounded. Missing evidence, exhausted budgets,
malformed outputs or provider failure cannot produce an unearned pass. SDK retries are disabled.
Trace records tool identifiers, safe arguments/counts, references, latency and outcome, not source
text, API keys, raw errors or hidden reasoning. Token accounting is currently not exposed by the
adapter contract: usage tokens are null and explicitly labelled, not claimed as zero actual usage.
Python cannot safely kill a timed-out adapter thread; late results are discarded, but a provider
may finish its request after interruption. Adapters must be read-only and never execute effects.

## One-round handoff and integration

1. Orchestrator submits proposal v1 and trusted fresh case state.
2. On `rejudge_requested`, persist state and pass the specific handoff/context to the real Judge.
3. Judge returns the same proposal ID at version +1, the previous proposal reference, exact
   rejudge request ID, and stable finding bindings. Scores/rationales/citations may change;
   reviewed transcript, scope and rubric may not.
4. Resubmit under the same case ID with the returned state. A pass requires fresh inspection and
   explicit resolution of previous objections. Removing a bad citation alone is not resolution.
5. A remaining issue or second rejudge attempt goes to professor review. Terminal state cannot
   be resubmitted. An audit pass never substitutes for professor approval.

**Persistence boundary:** this is an in-process harness, not durable case storage. The future
orchestrator must atomically claim a case/state version, deduplicate proposal/request IDs and
persist returned state before dispatching the Judge. Otherwise forged/reset/stale state or
concurrent invocations could create extra rounds. No worker or durable resume is implemented.

The existing `src/classpartai/agents/judge.py` and `agents/auditor.py` remain placeholders.
Their contract lacks the stable versioned identifiers needed here. The teammate supplies an
agreed mapping, reviewed inputs/rubric, an ownership-enforcing evidence reader, a real Judge
revision adapter and atomic state persistence. Do not map audit pass directly to grade approval.
The CLI's local JSON reader is a demonstration adapter, not authentication for a public endpoint.

## Optional explicit local mode

Without an explicit provider setting, operation defaults to OpenAI. Local mode is retained when explicitly selected:

```text
uv run python -B -m classpartai.auditor_agent src/classpartai/auditor_agent/examples/data/example_request.json --evidence src/classpartai/auditor_agent/examples/data/example_evidence.json --local-model YOUR_INSTALLED_LOCAL_MODEL
```

`--local-url` overrides the loopback `/v1` URL. Python callers can use
`AuditorAgent(reader, local=True)` with `AUDITOR_MODEL` and `AUDITOR_MODEL_URL`. These legacy
local settings do not override shared OpenAI settings in default mode. No automatic fallback
between providers occurs. Local URLs remain restricted to loopback HTTP, with no cloud routing.

## Verification and limits

40 Python 3.12 tests passed, including shared-key/model resolution, configuration precedence,
SDK-native function parsing, timeout/retry controls, an SDK-double complete audit with nested
citation review, secret-safe provider failure, prior citation/scope/rejudge/budget checks, and
a loopback HTTP protocol double. Fictional demo and CLI checks also passed.

Tests use labelled fictional fixtures/doubles. No paid OpenAI call was made, no real key was
validated, and live behaviour/account access remains unverified. The standalone Python interpreter
used here has no installed OpenAI SDK; root `uv sync` installs the already-declared dependency.
Ruff/uv are unavailable in this environment, so those checks were not run. Existing application
files, actual `.env`, shared manifests/lockfiles and staging were not modified.

Repository guidance, README, contracts and existing Action integration were inspected. No Nov 3
design photos, Topic 7 slides or Python lab were available locally. The implementation demonstrates
the specified observe/choose/execute loop, typed tools, memory, budgets and harness guardrails
without requiring MCP or LangGraph. No live superiority or semantic-review accuracy is claimed.


## Controlled tool-description, recovery and rubric-policy experiments

The three small changes are isolated by the caller-only `AuditTuning` settings in `harness.py`:

| Variant | Comparison trigger cue | Recover missing checks | Score-versus-citation instruction |
| --- | --- | --- | --- |
| `original` | Previous wording | Previous terminal escalation | Previous policy |
| `description_only` | New wording | Previous terminal escalation | Previous policy |
| `description_and_recovery` | New wording | Enabled | Previous policy |
| `all_three` (default) | New wording | Enabled | Enabled |

Each consecutive variant changes one factor. All use the same inputs, evidence corpus, model
adapter and budgets. The experiment controls cannot disable citation validation, ownership/scope
checks, score ranges, hard budgets or the one-rejudge limit. Tool definitions are copied per run;
variants do not mutate global schemas or affect concurrent runs.

`compare_similar` now says **when** it is useful and reminds the model to inspect context and
rubric descriptors before objecting. The Auditor policy separately instructs the model to compare
the observed contribution with the awarded rubric level. `verify_citation` remains a citation
support check, never a score validator or replacement Judge. Supply actual level descriptors in
the pinned criterion descriptions; range endpoints alone do not explain what top marks require.

A premature `complete_audit(audit_passed)` can now return:

```json
{
  "status": "pass_blocked",
  "missing_checks": {
    "finding_ids": ["finding-a"],
    "citations": [{"finding_id": "finding-a", "evidence_id": "evidence-a"}]
  },
  "message": "Inspect the missing items, observe the results, then decide how to finish."
}
```

The model receives this observation and may choose further investigation in the same run. It
uses the same remaining model-call, tool-step and elapsed-time budgets, not a new retry budget.
Only omissions are recoverable: confirmed unsupported/invalid evidence, attribution issues,
unresolved prior objections or deletion of a previously challenged citation still prevent a
pass and require targeted rejudge or professor review. Repeated early finishes terminate within
the budget. Trace marks the blocked attempt as `outcome: pass_blocked` and records safe IDs.

Run the fictional offline comparison or the explicit live comparison:

```text
uv run python -B -m classpartai.auditor_agent.examples.evaluation
uv run python -B -m classpartai.auditor_agent.examples.evaluation --live
```

The second command uses the selected hosted provider model/key and can incur API charges. With no key/SDK,
it returns `live_blocked` and no runs, not a substitute double. It never forces a live model to
compare peers, attempt early finish or follow a canned route.

Five cases cover a defensible score, supported definition with an overstated top score, genuine
scoring inconsistency, an unresolved issue after the allowed rejudge, and early finish. The pending
rejudge in the unresolved case is fictional prepared state, not a claimed live first audit.
`examples/data/evaluation_cases.json` contains the exact inputs and authored expected verdicts.
`examples/data/evaluation_offline.json` records the 20 offline runs: verdict, route, invalid calls, blocked-pass
observations, model/tool usage, latency and comparison counts. The comparison-usefulness fields
are fixture proxies; live reviewers must inspect objections and context, not just count calls.

Observed offline results with the **same deterministic double**, not an LLM:

| Variant | Matches authored verdict expectation | Early-finish result |
| --- | --- | --- |
| Original | 4/5 | Professor review |
| Description only | 4/5 | Professor review |
| Description + recovery | 5/5 | Audit pass after missing checks |
| All three | 5/5 | Audit pass after missing checks |

The double deliberately does not branch on prompt wording. Thus this comparison demonstrates the
actual recovery change, **not a measured benefit from either prompt change**. It compares peers
for the inconsistency case and skips comparison for the straightforward citation case in every
variant. The overstated score produces a rationale objection even though the citation supports
its factual claim. The unresolved revision escalates without a second rejudge. No replacement
score is generated.

The earlier live comparison was attempted and reported blocked: no usable shared key/SDK was available.
Live tool-selection quality, score-review accuracy, prompt gains and latency remain unverified.
Do not claim agentic superiority or treat 5/5 fictional-double outcomes as a model benchmark.

After the presentation-layout refactor, the same 40 tests, relocated demo/CLI and controlled
offline comparisons were checked again. Public `AuditorAgent` and `audit_proposal` imports remain
available; internal `model.py`, demo, evaluation and test paths changed as shown above.


## Live diagnosis: unavailable model, then rate limit

A real reproduction returned **404 `model_not_found`** before any tool executed. A bounded model-list
request authenticated the configured Groq key and confirmed that the configured model was absent
from the account's available models. Both `openai/gpt-oss-20b` and `openai/gpt-oss-120b` were listed.
The earlier suggested Llama model is not available through this account. The Groq default and
setup examples now use `openai/gpt-oss-20b`; an explicit `GROQ_MODEL` in `.env` still takes precedence.

Privately change the existing `.env` model entry, or override it for one run:

```text
GROQ_MODEL="openai/gpt-oss-20b"
```

```text
uv run python -B -m classpartai.auditor_agent src/classpartai/auditor_agent/examples/data/example_request.json --evidence src/classpartai/auditor_agent/examples/data/example_evidence.json --provider groq --model openai/gpt-oss-20b
```

The actual `.env` has not been edited by the agent. A bounded live audit with the model override
made **five model attempts and three outer tool steps**, choosing `get_session_scores`,
`verify_citation` (including nested semantic review), and `detect_injection`. The run then received
**429 `rate_limit_exceeded`**, with `Retry-After: 2` seconds. It ended safely with professor review,
not an audit pass. This demonstrates that the key/endpoint and available model can execute tools;
it does not establish a completed or correct live assessment. Model availability and quotas are
account-specific and may change. A retry hint is not a guarantee that the entire next audit will fit.

`harness.py` now records a `provider_error` trace event with a safe HTTP status/category, an
allowlisted provider code, and numeric `retry_after_seconds` when present. `agent.py` converts SDK
exceptions to this bounded diagnostic. Raw error messages, response bodies, generated text,
authorization headers and keys are never included. Invalid/unavailable models and rate limits
are now distinguishable. SDK automatic retries remain disabled; no fallback provider or second
rejudge is introduced. The tool-generation correction below is explicit and counted by the harness. After a failed terminal run, start a new audit from the original input;
there is no automatic durable resume.

All **50 offline tests passed**, including safe 404/429 diagnostics, retry hints and secret
redaction. Existing application files, manifests, lockfiles, `.env` and staging remain untouched.


## Native tool-call compatibility and bounded correction

A valid key/model can still produce a rejected function call (`400 tool_use_failed`). The model
chooses from `TOOLS` in `harness.py`; the harness executes matching functions in `tools.py` only
after a successful native response and Python validation. A rejected provider generation is never
converted into a tool invocation or silently repaired by editing its arguments.

Changes made to handle this failure:

- `agent.py` requests native strict function schemas for Groq GPT-OSS 20B/120B. It does not use
  prose parsing, JSON response-format simulation, or disable tool validation. Other providers
  keep their previous request configuration.
- Groq rejected two strict-schema details during verification: the no-argument `score_stats`
  schema with `required: []` and empty `properties`, and the `uniqueItems` keyword inside ID
  arrays. A provider-only schema copy omits these unsupported details. Empty required versus
  omitted required has the same meaning. Full Python uniqueness, ID, range, attribution and
  citation checks remain; the original `TOOLS` schemas are never mutated.
- Groq's completion cap is 2,048 and GPT-OSS reasoning effort is `low` to reduce token demand.
  These are generation settings, not a programmed investigation route.
- `harness.py` permits **one** correction for a provider-rejected tool generation across the
  whole run, including nested citation review. It returns trusted schema feedback listing
  exact tool names and required argument keys. The model must choose a new native call.
- The rejected request and correction each consume the shared model-call budget and elapsed
  time. There are no SDK retries, provider fallback, unlimited retries or extra rejudge rounds.
  Authentication, unavailable models, rate limits and other errors are not retried this way.
- Traces record `recovery: tool_schema_feedback` with safe provider diagnostics. Raw failed
  generations, hidden reasoning, prompts and secrets are not persisted or echoed.

Latest bounded live Groq test on the fictional input completed with `audit_passed` and
`model_completed_validated`. Observed route: `get_session_scores → verify_citation → complete_audit`.
There was one real `400 tool_use_failed`; the model recovered after schema feedback. Total usage:
**5 model attempts**, **3 executed outer tool steps**, approximately **3.17 seconds**. This is one
observed live trajectory, not a guarantee of future routes or independently validated audit quality.
The exact field in the user's earlier failed generation was not captured, so it is not claimed
as established. The reproducible strict-schema incompatibilities and bounded recovery were verified.

All **55 offline tests passed**, including provider-only schema projection, unchanged backend
constraints, secret protection, one shared correction limit, no rate-limit retry and SDK-level
recovery. A separate live comparison/benchmark across all evaluation cases has not been completed.

Run the same live example again:

```text
uv run python -B -m classpartai.auditor_agent src/classpartai/auditor_agent/examples/data/example_request.json --evidence src/classpartai/auditor_agent/examples/data/example_evidence.json --provider groq --model openai/gpt-oss-20b
```

For another provider/model, malformed calls can still occur. Keys authorise access; model/tool
reliability is a separate concern. The same Python checks continue to apply.


## Distinguishing a later generic HTTP 400

A reported run executed `get_session_scores` and then received `400 invalid_request`. That
category is broader than `tool_use_failed`; its trace alone does not establish a schema,
conversation-format or model-generation cause. A bounded reproduction using the same configured
GPT-OSS 20B model completed with `audit_passed` after one known tool-generation correction.
The specific generic 400 was not reproduced, so no exact cause or universal fix is claimed.

Safe diagnostics now recognise fixed provider-message signatures and return `request_issue`
labels: `invalid_tool_schema`, `required_tool_call_missing`, `unknown_generated_tool`, or
`generated_arguments_invalid_json`. Only known constant labels and allowlisted error codes are
shown; raw messages, generated text and keys remain private. Confirmed schema errors remain
non-retryable. Clearly identified generation failures can use the existing single shared repair;
this does not enable retries for arbitrary HTTP 400s. All **57 offline tests passed**.


## Tool-call quality improvements

The core files remain `agent.py`, `harness.py` and `tools.py`; no framework, dependency or provider
was added, and the model was not automatically upgraded.

- The prompt now explicitly requires exact native tool names, declared argument types, observed
  IDs and native completion/rejudge calls. This defines the action protocol, not an action order.
- Every tool description explains when it is useful. Comparison remains optional; statistics are
  suggested only where the data warrants them. The model still chooses which check to run next.
- The harness validates arguments against the same `TOOLS` schemas provided to the model, replacing
  a duplicated required-field table. Validation checks nested objects, required/unknown arguments,
  types, enums, bounds, lengths and duplicate IDs, including provider-omitted constraints.
- Invalid arguments receive a safe `tool_call_invalid` result identifying the schema field path
  and problem, such as `missing_required_arguments` with `missing_fields: ["evidence_id"]`.
  Rejected values, unknown argument names, source text and secrets are not echoed. Known context
  refusals distinguish wrong findings/citations from incomplete inspection, without exposing IDs.
- Malformed native responses (missing calls, duplicate JSON keys, non-finite arguments or invalid
  JSON) can use the same **single shared response-correction allowance** as a provider-rejected
  generation. Native correction feedback includes argument types as well as required fields.
  No failed arguments are invented, modified or executed. Invalid decoded tool calls consume the
  normal model/tool budgets and receive correction feedback within that bounded loop.
- A schema rejection cannot be relabelled as retryable merely because the provider supplied a
  `tool_use_failed` code. Authentication, missing models and 429 limits still stop rather than
  trigger uncontrolled retries or provider fallback. Mandatory citation checks and one rejudge
  remain enforced in Python.

The Auditor Python files were formatted and their lint issues corrected without disabling rules.
All **64 offline tests passed**. Scoped Ruff lint and formatting checks pass. The tests include
argument-level recovery, nested validation, duplicate-key rejection, safe errors and preserved
provider/rejudge/budget safeguards. The existing application files and staging were not changed.

Two bounded real Groq checks used fictional `defensible` and `overstated_score` inputs with the
same configured GPT-OSS 20B model. Both ended on **429 rate limits**, so their final audit verdicts
cannot be evaluated as substantive judgements. The first inspected findings and verified a citation,
then attempted its one schema correction for a missing required tool call before hitting the quota;
the second inspected findings and hit quota on the next model attempt. Neither reached a completed
assessment. This is evidence of remaining quota constraints, not demonstrated prompt gains or
model superiority. Earlier successful live trajectories remain individual observations.

For model comparison, keep the same fixtures, rubric, provider parameters and shared budgets, and
choose a model explicitly (for example `--model` with a Groq-supported ID). Inspect valid calls,
justified objections, unnecessary checks and recovery. A larger model does not fix an incompatible
schema and has not been selected or benchmarked automatically. If quota keeps interrupting runs,
resolve request/token allowance or pacing before drawing conclusions about assessment quality.


### Live fictional overstated-score experiment

`examples/data/live_overstated_score_request.json` is a fictional Judge proposal,
not an actual student assessment. The reviewed contribution only says "Observation
and interpretation." The Judge awards 3/3, while the exact rubric requires applying
the distinction to a concrete example with justification. The quoted definition is
valid, so the Auditor must distinguish citation support from score justification.
The original passing fixture is preserved.

Configure `AUDITOR_PROVIDER=groq`, `GROQ_API_KEY` and `GROQ_MODEL` privately in the
root `.env`. Do not put keys in JSON fixtures. From the repository root:

```bash
uv run python -B -m classpartai.auditor_agent src/classpartai/auditor_agent/examples/data/live_overstated_score_request.json --evidence src/classpartai/auditor_agent/examples/data/example_evidence.json --provider groq --model openai/gpt-oss-20b
```

Do not add `--test-double` for live execution. This bounded command makes actual
provider requests and consumes the account quota. There is no provider fallback.
Inspect `execution_label`, `verdict`, `stop_reason`, `rejudge_request`, and the tool
trace. A targeted rationale objection and `rejudge_requested` are the authored
expectation, not a forced route or a guaranteed live outcome. The model may choose
other checks or escalate. Provider failures are execution failures, not evidence
that the proposal is defensible. The CLI exit code alone does not establish success.

Offline validation of this fixture with `EvaluationDouble` produced
`get_session_scores → verify_citation → request_rejudge`. That double is scripted;
it verifies handoff mechanics, not live model judgement. No live provider call was
made when adding the fixture. Keep the same fixture, model and budget when comparing
runs; repeated standalone invocations do not durably enforce case state.


### Speaking-duration fairness scope

The integrated transcript provides no transcription-confidence metric. `score_stats` therefore
analyses scores versus speaking duration only. Confidence correlation and confidence-missingness
outputs have been removed, and no confidence field is sent to the model or new example requests.
The legacy `transcription_confidence` input remains optional and validated solely for compatibility
with existing callers and case fingerprints; it is ignored by the tools. This does not change
reviewed speaker attribution or the Judge's separate confidence in its proposed score.
