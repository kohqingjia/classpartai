"""Read-only inspectors for the seven agents. All judgements come from persisted records."""

import json
from datetime import UTC, datetime
from urllib.parse import urlencode

import streamlit as st

from classpartai.config import DATA_DIR
from classpartai.models import WORKFLOW_LIMITS
from classpartai.monitoring_ui import usage_panel
from classpartai.participation.coordinator import COORDINATOR_TOOLS
from classpartai.participation.delivery import DeliverySettings, feedback_email
from classpartai.participation.judge import FLAG_PREFIX, JUDGE_TOOLS
from classpartai.quotes import quote_html
from classpartai.retrieval import examined_of, searches_of
from classpartai.ui import STAGES, flow_html, vault_html
from classpartai.voices import enrolments, match_rows

AGENTS = [name for _, _, name, _ in STAGES]
TABS = ["Overview", *AGENTS]
TOPICS = {
    "Listener": "Topic 2 · Transformers",
    "Coordinator": "Topic 7 · Agents",
    "Evidence / Research": "Topic 8 · Agentic RAG",
    "Judge": "Topic 6 · LLM-as-judge",
    "Auditor": "Topic 6 · Evaluation",
    "Feedback writer": "Topic 7 · Agents",
    "Delivery": "Topic 9 · Ethics",
}
DESCRIPTIONS = {
    "Listener": "From a class recording to a transcript you can trust and review.",
    "Coordinator": "The planner chooses its next tool from what the last action returned.",
    "Evidence / Research": (
        "Follow every search from a question to a passage, a grade and a citation."
    ),
    "Judge": "Provisional findings, grounded in each student's own contributions.",
    "Auditor": "A second look at support, attribution and uncertainty before professor review.",
    "Feedback writer": "One student's strengths and next step, with the evidence kept in view.",
    "Delivery": "The exact version you approved, sent only to roster-managed recipients.",
}
ROLE_NAMES = {
    "Judge": "judge_agent",
    "Auditor": "finish_assessment_audit",
    "Feedback writer": "finish_student_feedback",
}
# Runs recorded before the Judge became an agent used one structured call under this name.
LEGACY_ROLE_NAMES = {"Judge": "finish_rubric_judgement"}
# Roles run as a multi-step agent rather than one structured call (the Auditor agent falls back
# to the single-call role above if it errors).
AGENT_ROLES = {"Auditor": ("auditor_agent", "finish_feedback_audit")}


def section(number, title, note=None):
    st.markdown(f"#### {number:02d} / {title}")
    if note:
        st.caption(note)


def empty(text):
    st.info(text, icon=":material/info:")


def raw(label, data):
    with st.expander(label):
        st.json(data, expanded=False)


def header(name, status):
    st.badge(TOPICS[name], color="gray")
    title, state = st.columns([4, 1])
    title.subheader(name)
    label = {"configuration_blocked": "setup needed"}.get(status, status.replace("_", " "))
    state.badge(label, color="blue")
    st.write(DESCRIPTIONS[name])


def run_progress(run):
    progress = dict(run["progress"])
    if run["status"] == "running":
        elapsed = (datetime.now(UTC) - datetime.fromisoformat(run["created_at"])).total_seconds()
        progress["elapsedSeconds"] = max(progress.get("elapsedSeconds", 0), elapsed)
    return progress


def budget_gauges(progress):
    for col, key, label in zip(
        st.columns(4),
        ("modelCalls", "toolCalls", "tokens", "seconds"),
        ("Model calls", "Tool calls", "Tokens", "Seconds"),
        strict=True,
    ):
        used = progress.get("elapsedSeconds", 0) if key == "seconds" else progress.get(key, 0)
        maximum = WORKFLOW_LIMITS[key]
        col.metric(label, f"{used:,.0f}", f"of {maximum:,}", delta_color="off")
        col.progress(min(1.0, max(0.0, used / maximum)))
    st.caption(f"Shared workflow budget · token usage: {progress.get('usageKind', 'reported')}")


def timeline(actions):
    if not actions:
        empty("No calls recorded yet. This timeline fills as the agent works.")
    for n, action in enumerate(actions, 1):
        outcome = action.get("outcome", "ok" if action.get("ok") else "refused")
        with st.expander(f"{n:02d} · {action['tool']} · {outcome}"):
            st.caption("Arguments received")
            args = action.get("requestedArguments", action.get("arguments", action.get("args", {})))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    pass
            st.json(args)
            st.caption("Returned result / refusal")
            result = action.get("output") or action.get(
                "result", action.get("summary", "Not recorded")
            )
            if isinstance(result, (dict, list)):
                st.json(result)
            else:
                st.text(str(result))


def role_calls(records, session_id, name, newest_first=True):
    roles = {ROLE_NAMES[name], LEGACY_ROLE_NAMES.get(name), *AGENT_ROLES.get(name, ())}
    return [
        (run, call)
        for run in records.runs(session_id)
        for call in (
            reversed(run["progress"].get("roleCalls", []))
            if newest_first
            else run["progress"].get("roleCalls", [])
        )
        if call["role"] in roles
    ]


def judge_trajectory(calls):
    """The Judge's turns in the order it took them: which tool, with what, and what came back."""
    for n, (run, call) in enumerate(calls, 1):
        requested = (call.get("calls") or [{}])[0]
        tool_name = requested.get("name") or call.get("role", "judge")
        with st.expander(f"{n:02d} · {tool_name} · {call['outcome']} · {run['id'][:8]}"):
            if call.get("reason"):
                st.warning(call["reason"])
            st.caption("Arguments received")
            args = requested.get("arguments", "{}")
            try:
                args = json.loads(args)
            except (TypeError, ValueError):
                pass
            st.json(args, expanded=False)
            st.caption("Returned result / refusal")
            st.json(call.get("output", "Not recorded"), expanded=False)
            if call.get("validation") not in (None, "not applicable", "pending"):
                st.caption(f"Validation: {call['validation']}")
    st.caption("Only public tool calls and results are recorded; no hidden reasoning.")


def role_trajectory(calls):
    if not calls:
        empty("No role call recorded. Older runs do not contain exact role inputs or outputs.")
    for n, (run, call) in enumerate(calls, 1):
        with st.expander(
            f"{n:02d} · attempt {call['attempt']} · {call['outcome']} · {run['id'][:8]}"
        ):
            st.caption(f"Validation: {call.get('validation', 'not recorded')}")
            if call.get("reason"):
                st.warning(call["reason"])
            st.caption("Exact instructions and input history")
            st.text(call["instructions"])
            st.json(call["history"], expanded=False)
            st.caption("Allowed response schema")
            st.json(call.get("schema", {}), expanded=False)
            st.caption("Structured calls returned")
            st.json(call.get("calls", []), expanded=False)
            if "output" in call:
                st.json(call["output"], expanded=False)
            st.caption("Only public structured results are recorded; no hidden reasoning.")


def guardrails(messages, policy):
    section(5, "Guardrails that fired", "Topic 9 · Ethics & prompt injection")
    if messages:
        for message in dict.fromkeys(messages):
            st.warning(message)
    else:
        st.caption("No guardrail event recorded for this view.")
    with st.expander("Always enforced"):
        st.write(policy)


def overview(records, session_id, inputs, live=None):
    st.caption("ASSESSMENT WORKSPACE / IS469")
    st.subheader("Every decision, in view.")
    st.write("Follow the evidence through seven agent views. Your approval remains the final gate.")
    links = {
        key: "?" + urlencode({"session": session_id, "step": "AI assessment", "agent": name})
        for key, _, name, _ in STAGES
    }
    # This HTML never includes a live counter or a changing event list.
    st.iframe(flow_html(links=links, banner="SELECT A STAGE TO INSPECT ITS WORK"), height=190)
    runs = records.runs(session_id)
    latest = records.latest_draft(session_id)
    cols = st.columns(4)
    cols[0].metric("Students", len(inputs.roster))
    cols[1].metric("Reviewed turns", len(inputs.transcript.turns))
    cols[2].metric("Evidence checks", len(records.evidence_runs(session_id)))
    cols[3].metric("Draft version", latest.version if latest else "—")
    with st.container(border=True):
        st.caption("CURRENT ACTIVITY")
        if live and live.get("error"):
            st.error(live["error"])
        elif runs:
            st.write(run_label(runs[0]))
        else:
            st.write("Ready to assess this discussion.")
            st.caption("The agents prepare a draft. You review and approve it.")
        if live and live.get("events"):
            kind, _ = list(live["events"])[-1]
            st.caption(EVENT_LABELS.get(kind, "Assessment in progress"))
    if latest:
        st.caption(
            f"Version {latest.version} is ready to inspect. Continue to Approve after review."
        )


def listener_view(records, session_id, inputs):
    diagnostics = records.listener_run(session_id)
    header("Listener", "reviewed transcript")
    section(
        1,
        "Inputs",
        "Preprocessing · Whisper encoder-decoder transformer (Topic 2) → "
        "speaker embeddings + cosine similarity (Topics 1/8)",
    )
    recording = DATA_DIR / "recordings" / f"{session_id}.wav"
    if recording.is_file():
        st.audio(str(recording))
    else:
        st.caption("No recording saved for this session. Imported/demo transcripts have no audio.")
    voices = enrolments()
    with st.expander(f"Enrolled voices · {len(voices)}"):
        if voices:
            st.dataframe(
                [{"Student ID": k, "Name": v["name"]} for k, v in voices.items()],
                hide_index=True,
                width="stretch",
            )
        else:
            st.caption("No enrolled voices.")
    section(2, "Tools it may call")
    st.code("Whisper → pyannote diarisation → SpeechBrain verification", language=None)
    st.caption("Fixed preprocessing pipeline; no planner or scoring tool.")
    section(3, "Trajectory / timeline")
    if diagnostics:
        if diagnostics.get("note"):
            st.warning(diagnostics["note"])
        with st.expander("Whisper segments", expanded=True):
            whisper = [
                {k: v for k, v in seg.items() if k != "words"}  # word timings: raw response
                for seg in diagnostics.get("whisper_segments", [])
            ]
            st.dataframe(whisper, hide_index=True, width="stretch")
        rows = match_rows(diagnostics)
        if rows:
            st.dataframe(rows, hide_index=True, width="stretch")
        raw("Original Listener response", diagnostics)
    else:
        empty("Listener diagnostics were not recorded for this imported or older session.")
    matching = (diagnostics or {}).get("matching")
    if matching and matching.get("per") == "speaker":
        st.caption(
            f"Each diarised speaker is named when its best voice has cosine ≥ "
            f"{matching['minScore']:g} and a lead of ≥ {matching['minMargin']:g} over the "
            "runner-up, otherwise unknown or ambiguous. Each line of 1 s or more is also scored "
            'on its own voice and becomes ambiguous ("vetoed") if that clearly names someone '
            "else. SpeechBrain's own verifier decision is kept under voice_matches → verifier "
            "in the raw response."
        )
    elif matching:
        st.caption(
            f"Per-sentence matching: the best voice needs cosine ≥ {matching['minScore']:g} and a "
            f"lead of ≥ {matching['minMargin']:g} over the runner-up, otherwise the line stays "
            "unknown (pyannote diarisation was unavailable for this recording)."
        )
    elif diagnostics:
        st.caption(
            "Diarised speakers were identified with SpeechBrain's verifier: exactly one accepted "
            "match names the speaker; none is unknown, several is ambiguous."
        )
    section(4, "Outputs", f"Reviewed transcript · {inputs.transcript.version}")
    names = {s.id: s.displayName for s in inputs.roster}
    for turn in inputs.transcript.turns:
        speaker = turn.speaker
        who = (
            names.get(speaker.studentId, speaker.studentId)
            if speaker.kind == "student"
            else speaker.label
        )
        label = " · not scored" if speaker.kind == "uncertain" else ""
        with st.container(border=True):
            st.caption(f"{turn.id} · {turn.startMs / 1000:g}–{turn.endMs / 1000:g}s · {who}{label}")
            st.text(turn.text)
    guardrails(
        [
            f"{t.id}: unknown/uncertain speaker — not scored."
            for t in inputs.transcript.turns
            if t.speaker.kind == "uncertain"
        ],
        "Uncertain speakers cannot establish a score. Attribution must be "
        "reviewed by the professor.",
    )


def coordinator_view(records, session_id, inputs):
    runs = records.runs(session_id)
    run = runs[0] if runs else None
    if len(runs) > 1:
        selected = st.selectbox(
            "Coordinator run",
            range(len(runs)),
            format_func=lambda i: f"{runs[i]['created_at']} · {runs[i]['status']}",
        )
        run = runs[selected]
    progress = run_progress(run) if run else {}
    header("Coordinator", run["status"] if run else "not started")
    budget_gauges(progress)
    if run:
        st.caption(f"Run {run['id']} · stop: {run['stop_reason'] or 'pending'}")
    if run:
        section(0, "Usage & trace", "Every model call and step of this run, kept in the database")
        usage_panel(records, run["id"], "coord")
    section(1, "Inputs")
    raw("Pinned roster, rubric and transcript", inputs.model_dump(exclude={"documents"}))
    raw(
        "Recorded coordinator instructions and initial history",
        progress.get("coordinatorInput", {}),
    )
    section(2, "Tools it may call", "The model chooses an action; the harness validates it.")
    st.dataframe(
        [{"Tool": t.name, "Purpose": t.description} for t in COORDINATOR_TOOLS],
        hide_index=True,
        width="stretch",
    )
    section(3, "Trajectory / timeline")
    timeline(progress.get("actions", []))
    section(4, "Outputs")
    st.text(f"Latest draft: {progress.get('latestDraftId') or 'No draft handed on'}")
    st.caption("Evidence runs handed back: " + ", ".join(progress.get("evidenceRunIds", [])))
    guardrails(
        [
            a.get("result", {}).get("error", a["summary"])
            for a in progress.get("actions", [])
            if a["outcome"] == "invalid"
        ]
        + (
            [f"Run stopped: {run['stop_reason']}"]
            if run
            and run["stop_reason"]
            not in (None, "ready_for_professor_review", "escalated_with_open_issues")
            else []
        ),
        "One shared budget covers all roles and research. Tools are schema checked. "
        "The coordinator cannot approve or send. Transcript and tool results are untrusted data.",
    )


def evidence_view(records, session_id, inputs):
    runs = records.evidence_runs(session_id)
    run = None
    if runs:
        pick = st.selectbox(
            "Evidence check",
            range(len(runs)),
            format_func=lambda i: f"{runs[i]['question']} · {runs[i]['status']}",
        )
        run = runs[pick]
    p = run["progress"] if run else {}
    bundle = p.get("bundle") or {}
    header("Evidence / Research", run["status"] if run else "not started")
    st.iframe(
        vault_html(
            inputs.documents,
            searches_of(p),
            examined_of(p),
            bundle.get("citations", []),
            height=420,
        ),
        height=424,
    )
    section(1, "Inputs")
    if run:
        st.text(run["question"])
    st.caption(
        f"{len(inputs.documents)} pinned course documents · {len(inputs.transcript.turns)} turns"
    )
    raw("Session documents and passages", [d.model_dump() for d in inputs.documents])
    section(2, "Tools it may call")
    st.code(
        "get_lesson_context · search_course_materials · search_web (when configured)\n"
        "grade_evidence · submit_findings",
        language=None,
    )
    st.caption(
        "Legacy evidence.py: search_course_passages · get_source_passage · finish_evidence. "
        "The actual calls below identify which agent ran."
    )
    section(
        3,
        "Trajectory / timeline",
        "BM25 keywords + vector cosine, ranked by reciprocal rank fusion",
    )
    passages = {f"{d.id}:{d.version}:{x.id}": x.text for d in inputs.documents for x in d.passages}
    searches = searches_of(p)
    if not searches:
        empty("No search trace recorded yet.")
    for i, search in enumerate(searches, 1):
        with st.expander(f"Search {i:02d} · {search['query']}", expanded=i == 1):
            for hit in search["hits"]:
                st.caption(
                    f"{hit['passageId']} · cosine: {hit.get('score', 'not recorded')} · "
                    f"BM25: {hit.get('bm25', 'not recorded')} · "
                    f"RRF: {hit.get('rrf', 'not recorded')}"
                )
                st.text(hit.get("text") or passages.get(hit["passageId"], "Passage not available"))
    timeline(p.get("actions", []))
    for pack in p.get("research", []) or []:
        with st.expander(f"Research pack · {pack.get('contribution_id') or pack.get('kind')}"):
            st.text("Question: " + (pack.get("question") or "Unprompted contribution"))
            st.text(pack.get("text", ""))
            st.caption(f"Route: {pack.get('route')} · {pack.get('route_reason')}")
            raw("Exact research model history", pack.get("model_history", []))
            timeline(pack.get("trajectory", []))
            for claim in [*pack.get("claims", []), *pack.get("expected_points", [])]:
                st.text(f"{claim.get('claim')} — {claim.get('status')}")
                st.json(claim.get("evidence", []), expanded=False)
            raw("Complete graded pack and handoff signals", pack)
    section(4, "Outputs", "Validated citations and gaps handed to the Judge")
    if bundle:
        st.text(bundle.get("explanation", ""))
        for cite in bundle.get("citations", []):
            with st.container(border=True):
                st.caption(f"{cite['title']} · p. {cite['page']} · {cite['relationship']}")
                st.text("“" + cite["excerpt"] + "”")
        for gap in bundle.get("gaps", []):
            st.warning("Gap: " + gap)
        for conflict in bundle.get("conflicts", []):
            st.warning("Conflict: " + conflict)
    else:
        st.caption("No evidence bundle handed on.")
    flagged = [
        a.get("summary", "Refused research action")
        for a in p.get("actions", [])
        if a.get("outcome") not in ("ok", "started")
    ]
    for pack in p.get("research", []) or []:
        flagged.extend(pack.get("notes", []))
    guardrails(
        flagged,
        "Quotes must be verbatim from retrieved passages in this session. "
        "Untrusted retrieved instructions cannot change the rubric. Weak "
        "evidence stays unverified.",
    )


def cited_evidence(records, session_id, inputs, item):
    turns = {t.id: t for t in inputs.transcript.turns}
    for tid in item.turnIds:
        st.caption("Cited turn · " + tid)
        st.text(turns[tid].text if tid in turns else "Turn unavailable")
    bundles = dict(records.evidence_for(session_id))
    for ref in item.citations:
        bundle = bundles.get(ref.evidenceRunId)
        cite = (
            next((c for c in bundle.citations if c.passageId == ref.passageId), None)
            if bundle
            else None
        )
        st.caption(f"Course citation · {ref.passageId}")
        st.text(cite.excerpt if cite else "Citation unavailable; review required")


def role_view(records, session_id, inputs, name):
    latest = records.latest_draft(session_id)
    calls = role_calls(records, session_id, name, newest_first=name != "Judge")
    if name == "Judge":  # the latest run's turns, in the order the Judge took them
        run_ids = {run["id"] for run, _ in calls}
        latest_run = next((r["id"] for r in records.runs(session_id) if r["id"] in run_ids), None)
        calls = [(run, call) for run, call in calls if run["id"] == latest_run]
    header(name, "draft available" if latest else "not started")
    section(1, "Inputs")
    recorded = next((c["inputs"] for _, c in calls if c.get("inputs") is not None), None)
    if recorded is not None:
        raw("Exact inputs from the latest recorded call", recorded)
    else:
        st.caption("Exact role inputs unavailable until a new role call is recorded.")
    raw("Pinned rubric", inputs.rubric.model_dump())
    section(2, "Tools it may call")
    if name == "Judge":
        st.dataframe(
            [{"Tool": t.name, "Purpose": t.description} for t in JUDGE_TOOLS],
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "An agent: it picks its next tool from each result. The harness validates every "
            "score and refuses a rule-breaking call with the reason. Topic 7 · Agents."
        )
    elif name == "Auditor":
        from classpartai.auditor_agent.harness import TOOLS

        st.code(", ".join(t["function"]["name"] for t in TOOLS), language=None)
        st.caption(
            "Le Yong's Auditor agent chooses one read-only tool at a time (citation checks "
            "include a nested model review) and can only raise issues, request one re-judge or "
            "escalate to the professor. Feedback drafts get a separate structured review "
            "(finish_feedback_audit). If the agent errors, the workflow falls back to the "
            f"single structured call {ROLE_NAMES[name]}. Topic 7 · Agents."
        )
    else:
        st.code(ROLE_NAMES[name], language=None)
        st.caption(
            "One structured role call, with one correction attempt if invalid. Topic 7 · Agents."
        )
    section(3, "Trajectory / timeline")
    if name == "Judge" and any(c["role"] == ROLE_NAMES[name] for _, c in calls):
        judge_trajectory(calls)
    else:
        role_trajectory(calls)
    section(
        4,
        "Outputs",
        f"Current draft · version {latest.version} · {latest.origin}" if latest else None,
    )
    if latest is None:
        empty("No draft yet. Generate an assessment or create a professor draft from Overview.")
    elif name == "Judge":
        findings = latest.content.findings
        st.dataframe(score_matrix(inputs, findings), hide_index=True, width="stretch")
        low, flagged = judge_attention(findings)
        counts = st.columns(2)
        counts[0].metric("Low confidence", low)
        counts[1].metric("Flagged for review", flagged)
        for s in inputs.roster:
            with st.expander(s.displayName):
                for f in findings:
                    if f.studentId != s.id:
                        continue
                    confidence = f" · {f.confidence} confidence" if f.confidence else ""
                    st.write(f"**{f.criterionId}** · {f.status.replace('_', ' ')}{confidence}")
                    st.markdown(quote_html(f.justification, said(inputs)), unsafe_allow_html=True)
                    cited_evidence(records, session_id, inputs, f)
                    for limitation in f.limitations:
                        st.caption(limitation)
        st.caption(
            "validate_proposal checks: roster and criterion IDs; duplicate findings; rubric "
            "range; own attributed turns; silence rules; null for insufficient evidence; "
            "course-citation snapshot. Saved drafts passed validation; incomplete coverage "
            "is assessed separately by audit_draft."
        )
    elif name == "Auditor":
        issues = latest.content.audit.issues
        counts = st.columns(3)
        counts[0].metric(
            "Blocking / open",
            sum(i.severity == "blocking" and i.disposition == "open" for i in issues),
        )
        counts[1].metric(
            "Review / open", sum(i.severity == "review" and i.disposition == "open" for i in issues)
        )
        counts[2].metric("Resolved / revised", sum(i.disposition == "revised" for i in issues))
        for issue in sorted(
            issues, key=lambda i: (i.severity != "blocking", i.disposition != "open")
        ):
            origin = "Model-raised" if issue.id.startswith("model:") else "Deterministic"
            with st.container(border=True):
                st.caption(
                    f"{issue.severity.upper()} · {origin} · "
                    f"{'resolved (revised)' if issue.disposition == 'revised' else 'open'} "
                    f"· {issue.id}"
                )
                st.text(issue.detail)
                if issue.resolution:
                    st.text("Resolution: " + issue.resolution)
        st.caption(latest.content.audit.notes)
        raw(
            "Audit history by draft version",
            [
                {"version": d.version, "audit": d.content.audit.model_dump()}
                for d in records.drafts(session_id)
            ],
        )
    else:
        for s in inputs.roster:
            fb = next((f for f in latest.content.feedback if f.studentId == s.id), None)
            with st.expander(s.displayName, expanded=True):
                if fb:
                    st.caption("STRENGTHS")
                    st.text(fb.strengths)
                    st.caption("NEXT STEP")
                    st.text(fb.nextStep)
                    for limitation in fb.limitations:
                        st.caption(limitation)
                    cited_evidence(records, session_id, inputs, fb)
                else:
                    st.caption("No feedback drafted for this student.")
        for _, call in calls:
            result = call.get("output", {}).get("result", {})
            if result.get("status") == "needs_evidence":
                st.warning("Needs evidence: " + result["question"])
    fired = [c["reason"] for _, c in calls if c.get("reason")]
    if name == "Auditor" and latest:
        fired += [i.detail for i in latest.content.audit.issues if i.disposition == "open"]
    guardrails(
        fired,
        {
            "Judge": "Scores are provisional. Insufficient evidence is never zero. "
            "No score from an "
            "uncertain speaker or another student's turn. Deterministic "
            "validation is authoritative.",
            "Auditor": "Verify first, judge last. Model issues request review; "
            "they never lower scores. "
            "A model audit is not professor approval.",
            "Feedback writer": "Never name another student. "
            "Only the student's own turns and approved "
            "learning goals may be cited. Silence does not imply poor understanding.",
        }[name],
    )


def delivery_view(records, session_id, inputs):
    latest = records.latest_draft(session_id)
    approval = records.active_approval(session_id)
    settings = DeliverySettings.from_env()
    deliveries = records.deliveries(session_id)
    header("Delivery", "approved" if approval else "awaiting approval")
    st.badge("Test mode" if settings.test_mode else "Live mode", color="orange")
    if settings.test_mode:
        st.caption(
            f"All sends redirect to: {settings.test_recipient or 'test inbox not configured'}"
        )
    section(1, "Inputs", "Exact content + roster recipients + recipient revisions → SHA-256")
    recipients = records.recipients(session_id)
    st.dataframe(recipients or [{"Recipients": "Not set"}], hide_index=True, width="stretch")
    if latest:
        st.caption(f"Version {latest.version} · current digest")
        st.code(records.approval_digest(latest.content, recipients), language=None, wrap_lines=True)
    if approval:
        st.caption("Approved digest")
        st.code(approval["digest"], language=None, wrap_lines=True)
    section(2, "Tools it may call")
    st.code("Professor: approve_draft → deliver_approved → AgentMail transport", language=None)
    st.caption("Deterministic delivery service. No model has approval or send tools.")
    section(3, "Trajectory / timeline")
    raw("Approval history (including invalidated versions)", records.approvals(session_id))
    raw("Delivery attempts", records.attempts(session_id))
    st.caption("Send states: sending → accepted / rejected / ambiguous")
    section(4, "Outputs", "Email previews use the same formatter as delivery.")
    if latest:
        for s in inputs.roster:
            with st.expander(f"Email preview · {s.displayName}"):
                if any(f.studentId == s.id for f in latest.content.feedback):
                    st.text(feedback_email(records, session_id, s.id, latest))
                else:
                    st.caption("No email preview: feedback has not been drafted.")
    if deliveries:
        st.dataframe(deliveries, hide_index=True, width="stretch")
    else:
        st.caption("No send attempted.")
    guardrails(
        [
            f"{d['student_id']}: {d['state']}"
            for d in deliveries
            if d["state"] in ("ambiguous", "rejected")
        ],
        "Approval must match the latest content and recipients exactly. "
        "An edit invalidates approval. "
        "Accepted means provider acceptance, not inbox delivery. Accepted sends are never resent; "
        "ambiguous outcomes are never retried automatically.",
    )


def inspect_agent(name, records, session_id, inputs, live=None):
    if name == "Listener":
        listener_view(records, session_id, inputs)
    elif name == "Coordinator":
        coordinator_view(records, session_id, inputs)
    elif name == "Evidence / Research":
        evidence_view(records, session_id, inputs)
        if live and live["thread"].is_alive():
            with st.expander("Live research activity", expanded=True):
                for kind, detail in list(live.get("events", [])):
                    if kind in ("substep", "retrieval"):
                        st.json({"event": kind, **detail}, expanded=False)
    elif name in ROLE_NAMES:
        role_view(records, session_id, inputs, name)
    elif name == "Delivery":
        delivery_view(records, session_id, inputs)


EVENT_LABELS = {
    "thinking": "Coordinator is choosing the next action",
    "substep": "Research is checking a source",
    "retrieval": "Research retrieved course passages",
    "action": "Coordinator completed an action",
    "done": "Run finished",
}
HANDOFFS = {
    "Listener": "Recording → reviewed transcript → Coordinator",
    "Coordinator": "Reviewed inputs → tool decisions → assessment draft",
    "Evidence / Research": "Class contributions + course notes → cited evidence → Judge",
    "Judge": "Transcript + evidence + rubric → provisional findings → Auditor",
    "Auditor": "Draft + evidence → review issues → professor",
    "Feedback writer": "Findings + learning goals → personal feedback → professor",
    "Delivery": "Approved version + roster recipients → individual emails",
}


def run_label(run):
    if run["stop_reason"] == "model_not_configured":
        return "Connect an AI model to generate an assessment."
    if run["status"] == "running":
        return "Assessment in progress. You can explore each agent as it works."
    if run["stop_reason"] == "ready_for_professor_review":
        return "The assessment is ready for your review."
    if run["stop_reason"] == "escalated_with_open_issues":
        return (
            "Ready for your review, with open issues the agents couldn't resolve. Approval stays "
            "locked while any issue is blocking."
        )
    return "Run " + run["status"].replace("_", " ") + ". See inspection details for the reason."


def said(inputs):
    """Turn ID → what was said, for showing quotes instead of IDs."""
    return {t.id: t.text for t in inputs.transcript.turns}


def result_card(title, text, note=None, turns=None):
    with st.container(border=True):
        st.caption(title)
        if turns:
            st.markdown(quote_html(text, turns), unsafe_allow_html=True)
        else:
            st.write(text)
        if note:
            st.caption(note)


def judge_attention(findings):
    """(low-confidence findings, findings the Judge flagged for the professor)."""
    low = sum(f.confidence == "low" for f in findings)
    flagged = sum(any(x.startswith(FLAG_PREFIX) for x in f.limitations) for f in findings)
    return low, flagged


def score_matrix(inputs, findings):
    rows = []
    for student in inputs.roster:
        row = {"Student": student.displayName}
        for criterion in inputs.rubric.criteria:
            finding = next(
                (
                    f
                    for f in findings
                    if f.studentId == student.id and f.criterionId == criterion.id
                ),
                None,
            )
            row[criterion.title] = (
                f"{finding.score:g} / {criterion.maxScore:g}"
                if finding and finding.status == "scored"
                else "Insufficient evidence"
                if finding
                else "Not assessed"
            ) + (" · low confidence" if finding and finding.confidence == "low" else "")
        rows.append(row)
    return rows


def delivery_summary(records, session_id, inputs):
    latest = records.latest_draft(session_id)
    approval = records.active_approval(session_id)
    settings = DeliverySettings.from_env()
    cols = st.columns(3)
    cols[0].metric("Version", latest.version if latest else "—")
    cols[1].metric("Approval", "Approved" if approval else "Pending")
    cols[2].metric("Mode", "Test" if settings.test_mode else "Live")
    if latest:
        result_card(
            "Exact-version approval",
            "This version is approved."
            if approval
            else "Professor approval is required before sending.",
            "Editing content or recipients invalidates approval.",
        )
        with st.expander("Preview individual emails"):
            student = st.selectbox(
                "Student",
                inputs.roster,
                format_func=lambda s: s.displayName,
                key=f"email-preview-{session_id}",
            )
            if any(f.studentId == student.id for f in latest.content.feedback):
                st.text(feedback_email(records, session_id, student.id, latest))
            else:
                st.caption("Feedback has not been drafted for this student.")
    else:
        result_card("Waiting for a draft", "Generate an assessment from Overview to begin review.")
    deliveries = records.deliveries(session_id)
    if deliveries:
        names = {s.id: s.displayName for s in inputs.roster}
        st.dataframe(
            [
                {"Student": names.get(d["student_id"], d["student_id"]), "State": d["state"]}
                for d in deliveries
            ],
            hide_index=True,
            width="stretch",
        )
    if settings.test_mode:
        st.caption(
            "Test emails go to " + (settings.test_recipient or "a test inbox (not configured yet)")
        )
    st.caption("Ambiguous sends are never retried automatically.")


def presentation_agent(name, records, session_id, inputs, live=None):
    """A presentation-sized result; the full recorded anatomy is one switch away."""
    latest = records.latest_draft(session_id)
    runs = records.runs(session_id)
    evidence = records.evidence_runs(session_id)
    status = (
        "professor draft"
        if latest and latest.origin == "professor"
        else "draft available"
        if latest
        else "waiting"
    )
    if name == "Listener":
        status = "transcript available"
    elif name == "Coordinator":
        status = runs[0]["status"] if runs else "ready"
    elif name == "Evidence / Research":
        status = evidence[0]["status"] if evidence else "ready"
    elif name == "Delivery":
        status = "approved" if records.active_approval(session_id) else "awaiting approval"
    header(name, status)
    st.caption(HANDOFFS[name])
    if name == "Listener":
        turns = inputs.transcript.turns
        unknown = sum(t.speaker.kind == "uncertain" for t in turns)
        cols = st.columns(3)
        cols[0].metric("Transcript turns", len(turns))
        cols[1].metric("Students", len(inputs.roster))
        cols[2].metric("Unknown · not scored", unknown)
        recording = DATA_DIR / "recordings" / f"{session_id}.wav"
        if recording.is_file():
            st.audio(str(recording))
        else:
            st.caption("Imported transcript · no recording attached")
        names = {s.id: s.displayName for s in inputs.roster}
        for t in turns[:2]:
            speaker = t.speaker
            who = (
                names.get(speaker.studentId, speaker.studentId)
                if speaker.kind == "student"
                else speaker.label
            )
            result_card(who + (" · not scored" if speaker.kind == "uncertain" else ""), t.text)
        with st.expander(f"Read all {len(turns)} turns"):
            for t in turns:
                speaker = t.speaker
                who = (
                    names.get(speaker.studentId, speaker.studentId)
                    if speaker.kind == "student"
                    else speaker.label
                )
                st.caption(who + (" · not scored" if speaker.kind == "uncertain" else ""))
                st.text(t.text)
    elif name == "Coordinator":
        progress = runs[0]["progress"] if runs else {}
        result_card(
            "Current state",
            run_label(runs[0]) if runs else "Ready to plan the assessment.",
            "Each returned result informs the next tool choice.",
        )
        cols = st.columns(3)
        cols[0].metric("Model calls", progress.get("modelCalls", 0))
        cols[1].metric("Tool calls", progress.get("toolCalls", 0))
        cols[2].metric("Draft version", latest.version if latest else "—")
        actions = progress.get("actions", [])
        if actions:
            with st.expander(f"Recent decisions · {len(actions)} actions"):
                for a in actions[-3:]:
                    st.caption(a["tool"].replace("_", " ") + " · " + a["outcome"])
                    st.text(a["summary"])
        if live and live.get("events"):
            st.caption(EVENT_LABELS.get(list(live["events"])[-1][0], "Working"))
    elif name == "Evidence / Research":
        p = evidence[0]["progress"] if evidence else {}
        bundle = p.get("bundle") or {}
        st.iframe(
            vault_html(
                inputs.documents,
                searches_of(p),
                examined_of(p),
                bundle.get("citations", []),
                height=340,
            ),
            height=344,
        )
        cols = st.columns(3)
        cols[0].metric("Searches", len(searches_of(p)))
        cols[1].metric("Citations", len(bundle.get("citations", [])))
        cols[2].metric("Evidence gaps", len(bundle.get("gaps", [])))
        if live and live["thread"].is_alive():
            events = list(live.get("events", []))
            searches = sum(kind == "retrieval" for kind, _ in events)
            st.caption(f"Run in progress · {searches} searches returned so far")
        if bundle:
            result_card(
                "Research finding", bundle.get("explanation") or "Evidence bundle recorded."
            )
            if bundle.get("gaps"):
                with st.expander("Evidence gaps to review"):
                    for gap in bundle["gaps"]:
                        st.text(gap)
        else:
            st.caption(
                "Course notes are ready. Retrieved and cited passages appear "
                "here when research runs."
            )
    elif name == "Delivery":
        delivery_summary(records, session_id, inputs)
    elif latest is None:
        result_card(
            "Waiting for assessment",
            {
                "Judge": "Rubric scores will appear here, with evidence behind each decision.",
                "Auditor": "Open issues and their severity will appear here before you approve.",
                "Feedback writer": "Each student will receive a strength and a specific next step.",
            }[name],
            "Start from Overview → Generate assessment.",
        )
    elif name == "Judge":
        st.caption(f"PROVISIONAL FINDINGS · VERSION {latest.version}")
        st.dataframe(
            score_matrix(inputs, latest.content.findings), hide_index=True, width="stretch"
        )
        low, flagged = judge_attention(latest.content.findings)
        if low or flagged:
            st.caption(f"{low} low-confidence and {flagged} flagged findings need a closer look.")
        st.caption(
            "Insufficient evidence is never treated as zero. "
            "Open inspection details for justifications and citations."
        )
    elif name == "Auditor":
        issues = latest.content.audit.issues
        cols = st.columns(3)
        cols[0].metric(
            "Blocking", sum(i.severity == "blocking" and i.disposition == "open" for i in issues)
        )
        cols[1].metric(
            "For review", sum(i.severity == "review" and i.disposition == "open" for i in issues)
        )
        cols[2].metric("Resolved", sum(i.disposition == "revised" for i in issues))
        st.caption(
            "Deterministic checks + model audit recorded"
            if latest.content.audit.modelReviewed
            else "Deterministic checks recorded · model audit pending"
        )
        open_issues = [i for i in issues if i.disposition == "open"]
        if open_issues:
            with st.expander(f"Review {len(open_issues)} open issues"):
                for issue in open_issues:
                    st.caption(
                        issue.severity.upper()
                        + " · "
                        + ("Model-raised" if issue.id.startswith("model:") else "Deterministic")
                    )
                    st.text(issue.detail)
        else:
            result_card(
                "Audit result",
                "No open issues in this draft.",
                "Professor approval is still required.",
            )
    elif name == "Feedback writer":
        student = st.selectbox(
            "Student",
            inputs.roster,
            format_func=lambda s: s.displayName,
            key=f"feedback-preview-{session_id}",
        )
        feedback = next((f for f in latest.content.feedback if f.studentId == student.id), None)
        if feedback:
            result_card("Strength", feedback.strengths, turns=said(inputs))
            result_card("Next step", feedback.nextStep, turns=said(inputs))
        else:
            result_card("Feedback pending", "No feedback has been drafted for this student.")
        st.caption("Private to this student · never names other students")


def render_agent(name, records, session_id, inputs, live=None):
    inspect = st.toggle(
        "Inspect details",
        key=f"inspect-{session_id}-{name}",
        help="Open inputs, tools, complete trajectory, outputs and guardrails.",
    )
    if inspect:
        inspect_agent(name, records, session_id, inputs, live)
    else:
        presentation_agent(name, records, session_id, inputs, live)
