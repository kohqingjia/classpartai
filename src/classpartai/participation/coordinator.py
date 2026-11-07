"""The participation coordinator agent (ported from participation/coordinator.server.ts).

The coordinator chooses its own route: inspect the transcript, retrieve course evidence (via
the evidence agent), run the judge, audit, revise, draft each student's feedback, and finally
hand everything to the professor. It has no approval or delivery tools.

``on_event(kind, detail)`` lets the UI animate the run: "thinking" before each model call,
"action" after each tool call (detail = the action record), "substep" for each tool the
evidence agent runs inside retrieve_evidence, "retrieval" for each course search, "done" at
the end. Every event is also stored with its time (``Records.run_events``) for replay.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from classpartai import config
from classpartai import usage as ledger
from classpartai.evidence import INSTRUCTIONS as EVIDENCE_INSTRUCTIONS
from classpartai.evidence import TOOL_DEFINITIONS as EVIDENCE_TOOLS
from classpartai.evidence import CourseIndex, Investigation, investigate
from classpartai.models import (
    WORKFLOW_LIMITS,
    BudgetExceeded,
    SharedBudget,
    WorkflowProgress,
    configured_driver,
    tool,
)
from classpartai.participation.auditor_bridge import AuditorSession, agent_audit
from classpartai.participation.judge import Revision, judge
from classpartai.participation.records import Draft, Records
from classpartai.participation.roles import (
    ROLE_POLICY,
    DriverFactory,
    feedback_for,
)
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import Unprocessable, audit_draft
from classpartai.retrieval import searches_of


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Inspect(Strict):
    studentId: str | None = Field(max_length=80)
    turnIds: list[str] = Field(max_length=12)


class Retrieve(Strict):
    question: str = Field(min_length=5, max_length=1500)
    turnIds: list[str] = Field(min_length=1, max_length=8)
    criterionIds: list[str] = Field(min_length=1, max_length=6)
    reuseRunId: str | None


class Revise(Strict):
    note: str = Field(min_length=3, max_length=1000)


class Student(Strict):
    studentId: str = Field(min_length=1, max_length=80)


class Review(Strict):
    summary: str = Field(min_length=5, max_length=1500)


COORDINATOR_TOOLS = [
    tool(
        "inspect_transcript_context",
        "Inspect reviewed attribution and neighbouring turns instead of searching course "
        "sources unnecessarily",
        Inspect,
    ),
    tool(
        "retrieve_evidence",
        "Reuse a relevant existing validated run, or invoke the bounded course evidence agent "
        "for a question",
        Retrieve,
    ),
    tool(
        "propose_rubric_assessment",
        "Invoke the provisional rubric judge, including revisions after audit findings",
        Revise,
    ),
    tool(
        "audit_assessment",
        "Run deterministic and model review of support, contradictions and feedback; never "
        "automatically lower scores",
        Revise,
    ),
    tool(
        "draft_student_feedback",
        "Ask the feedback role to draft for one roster student or request missing evidence",
        Student,
    ),
    tool(
        "request_professor_review",
        "Finish only when all required findings/feedback and an audit are ready; never approve "
        "or send",
        Review,
    ),
]
COORDINATOR_POLICY = (
    f"{ROLE_POLICY}\nGoal: prepare fair evidence-supported provisional participation findings "
    "and useful individual feedback for EVERY roster student, ready for professor review. Choose "
    "your next action based on tool results, not a fixed sequence. You may inspect context, "
    "reuse evidence, retrieve more, judge, audit, revise, request more evidence before feedback, "
    "or finish with unresolved uncertainty for professor review. Audit support and "
    "contradictions as well as deterministic validity. No-observation findings are not "
    "poor-understanding claims. Tool results must be inspected before choosing another action. "
    "There are no approval or delivery tools. Use request_professor_review when required drafts "
    "and an audit exist; unresolved issues remain visible. Do not call all tools mechanically."
)
PROMPT_VERSION = "participation-coordinator-v1"


def coordinate(
    records: Records,
    session_id: str,
    factory: DriverFactory = configured_driver,
    on_event: Callable[[str, dict | None], None] = lambda kind, detail: None,
) -> str:
    """Run the workflow for one session; returns the participation run ID."""
    # Every model call and step inside is recorded against this run (usage.py, Monitoring page).
    with ledger.tracking(session_id=session_id, agent="coordinator", sink=records.log_event):
        return _coordinate(records, session_id, factory, on_event)


def _coordinate(
    records: Records,
    session_id: str,
    factory: DriverFactory,
    on_event: Callable[[str, dict | None], None],
) -> str:
    inputs = records.inputs(session_id)
    records.review_state(session_id)
    progress = WorkflowProgress()
    run_id = records.start_run(
        session_id,
        {
            "transcriptVersion": inputs.transcript.version,
            "rubricId": inputs.rubric.id,
            "rubricVersion": inputs.rubric.version,
            "promptVersion": PROMPT_VERSION,
            "model": config.OPENAI_MODEL,
            "judgeReasoningEffort": config.JUDGE_REASONING_EFFORT,
        },
        WORKFLOW_LIMITS["seconds"],
    )
    ledger.update(run_id=run_id)

    started = time.monotonic()
    seq = [0]

    def emit(kind: str, detail: dict | None) -> None:
        """Show the event live, and keep it (slimmed to what the UI reads) for replay."""
        on_event(kind, detail)
        kept = detail
        if kind == "action":
            kept = {k: detail.get(k) for k in ("id", "tool", "arguments", "outcome", "summary")}
            result = detail.get("result")
            if isinstance(result, dict) and result.get("draftId"):
                kept["draftId"] = result["draftId"]
        try:
            records.append_run_event(run_id, seq[0], time.monotonic() - started, kind, kept)
        except Exception:  # a replay record must never stop the run itself
            pass
        seq[0] += 1

    def checkpoint() -> None:
        progress.elapsedSeconds = round(time.monotonic() - started, 3)
        records.update_run(run_id, asdict(progress))

    try:
        driver = factory(COORDINATOR_POLICY, COORDINATOR_TOOLS)
    except Exception:
        driver = None
    if driver is None:
        records.update_run(
            run_id, asdict(progress), "configuration_blocked", "model_not_configured"
        )
        emit("done", {"stopReason": "model_not_configured"})
        return run_id

    budget = SharedBudget(progress, time.monotonic() + WORKFLOW_LIMITS["seconds"], checkpoint)
    index = CourseIndex(inputs)
    existing = records.evidence_for(session_id)
    history: list[dict] = [
        {
            "role": "user",
            "content": json.dumps(
                {
                    "untrustedData": {
                        "sessionId": session_id,
                        "roster": [s.model_dump() for s in inputs.roster],
                        "rubric": inputs.rubric.model_dump(),
                        "transcriptVersion": inputs.transcript.version,
                        "turnIds": [t.id for t in inputs.transcript.turns],
                        "evidenceRuns": [
                            {
                                "id": run,
                                "question": b.question,
                                "status": b.status,
                                "gaps": b.gaps,
                            }
                            for run, b in existing
                        ],
                    }
                }
            ),
        }
    ]
    progress.coordinatorInput = {"instructions": COORDINATOR_POLICY, "history": history.copy()}
    checkpoint()
    turns = inputs.transcript.turns
    auditor = AuditorSession()  # one-round re-judge state, for this run only
    review_refusals = 0
    stop_reason = "shared_budget_exhausted"
    try:
        while True:
            if budget.expired():
                raise BudgetExceeded()
            emit("thinking", None)
            response = budget.call(driver, history)
            budget.tool()
            if len(response.calls) != 1:
                raise RuntimeError("Coordinator must choose one tool action at a time")
            call = response.calls[0]
            names = {t.name for t in COORDINATOR_TOOLS}
            action = {
                "id": f"{progress.toolCalls}:{call.call_id}",
                "tool": call.name if call.name in names else "unsupported_tool",
                "arguments": "{}",
                "requestedArguments": call.arguments,
                "summary": "Action requested",
                "outcome": "started",
            }
            progress.actions.append(action)
            checkpoint()
            step_started = ledger.begin()
            history.append(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": call.arguments,
                }
            )
            finished = False
            try:
                raw = json.loads(call.arguments)
                draft = records.latest_draft(session_id)
                if call.name == "inspect_transcript_context":
                    args = _arguments(Inspect, raw)
                    action["arguments"] = args.model_dump_json()
                    if args.studentId is not None and not any(
                        s.id == args.studentId for s in inputs.roster
                    ):
                        raise Unprocessable("Unknown roster student")
                    ids = {t.id for t in turns}
                    if any(i not in ids for i in args.turnIds):
                        raise Unprocessable("Unknown transcript turn")
                    output = {
                        "reviewedTurns": [
                            t.model_dump()
                            for i, t in enumerate(turns)
                            if t.id in args.turnIds
                            or (
                                args.studentId is not None
                                and t.speaker.kind == "student"
                                and t.speaker.studentId == args.studentId
                            )
                            or turns[max(0, i - 1)].id in args.turnIds
                            or turns[min(len(turns) - 1, i + 1)].id in args.turnIds
                        ][:20],
                        "limits": "At most 20 context turns; inspect more stable IDs if needed",
                    }
                elif call.name == "retrieve_evidence":
                    args = _arguments(Retrieve, raw)
                    action["arguments"] = args.model_dump_json()
                    if args.reuseRunId:
                        bundle = dict(records.evidence_for(session_id)).get(args.reuseRunId)
                        if bundle is None:
                            raise Unprocessable(
                                "Existing evidence is unavailable for this snapshot"
                            )
                        output = {"id": args.reuseRunId, "bundle": bundle.model_dump()}
                    else:
                        use_research = config.EVIDENCE_AGENT == "research"
                        evidence_driver = (
                            None if use_research else factory(EVIDENCE_INSTRUCTIONS, EVIDENCE_TOOLS)
                        )
                        if evidence_driver is None and not use_research:
                            raise RuntimeError("Model configuration blocked")
                        request = Investigation(
                            sessionId=session_id,
                            question=args.question,
                            turnIds=args.turnIds,
                            criterionIds=args.criterionIds,
                        )
                        before, searches_seen = 0, 0

                        def count_tools(p):
                            # Evidence-agent tool calls count against the shared budget too.
                            nonlocal before, searches_seen
                            searches = searches_of(p)
                            for search in searches[searches_seen:]:
                                emit("retrieval", search)
                            searches_seen = len(searches)
                            if p.toolCalls > before:
                                budget.tool(p.toolCalls - before)
                                before = p.toolCalls
                                tool_name = getattr(p, "lastTool", None) or (
                                    p.actions[-1]["tool"] if p.actions else "working"
                                )
                                emit("substep", {"tool": tool_name, "step": p.toolCalls})

                        if use_research:  # ② Research (research/bridge.py), same contract
                            from classpartai.research import bridge

                            outcome = bridge.investigate(request, inputs, budget, count_tools)
                        else:
                            outcome = investigate(
                                request, inputs, budget.wrap(evidence_driver), index, count_tools
                            )
                        evidence_run = records.save_evidence_run(session_id, args.question, outcome)
                        progress.evidenceRunIds.append(evidence_run)
                        output = {
                            "id": evidence_run,
                            "status": outcome.status,
                            "bundle": outcome.progress.bundle.model_dump(),
                        }
                elif call.name == "propose_rubric_assessment":
                    args = _arguments(Revise, raw)
                    action["arguments"] = args.model_dump_json()
                    # A revision tells the Judge what the audit objected to, so it re-scores only
                    # those students instead of everyone.
                    revision = (
                        Revision(args.note, draft.content.findings, draft.content.audit.issues)
                        if draft
                        else None
                    )
                    judged = judge(
                        inputs,
                        records.evidence_for(session_id),
                        budget,
                        factory,
                        session_id,
                        revision,
                    )
                    judged.feedback = draft.content.feedback if draft else []
                    nxt = records.append_draft(
                        session_id, judged, "model", args.note, draft.version if draft else 0
                    )
                    progress.latestDraftId = nxt.id
                    output = {
                        "draftId": nxt.id,
                        "findings": [f.model_dump() for f in nxt.content.findings],
                        "auditIssues": [i.model_dump() for i in nxt.content.audit.issues],
                    }
                elif call.name == "audit_assessment":
                    args = _arguments(Revise, raw)
                    action["arguments"] = args.model_dump_json()
                    if draft is None:
                        raise Unprocessable("Create a provisional draft before audit")
                    # Le Yong's Auditor agent; falls back to the single-call model_audit.
                    audit = agent_audit(
                        inputs,
                        draft.content,
                        records.evidence_for(session_id),
                        budget,
                        factory,
                        session_id=session_id,
                        draft_id=draft.id,
                        session=auditor,
                    )
                    nxt = records.append_draft(
                        session_id, _proposal(draft), "model", args.note, draft.version, audit
                    )
                    progress.latestDraftId = nxt.id
                    output = {"draftId": nxt.id, "audit": nxt.content.audit.model_dump()}
                elif call.name == "draft_student_feedback":
                    args = _arguments(Student, raw)
                    action["arguments"] = args.model_dump_json()
                    if draft is None:
                        raise Unprocessable("Create findings before feedback")
                    result = feedback_for(
                        args.studentId,
                        inputs,
                        _proposal(draft),
                        records.evidence_for(session_id),
                        budget,
                        factory,
                        session_id,
                    )
                    if result.status == "needs_evidence":
                        output = result.model_dump()
                    else:
                        if result.feedback.studentId != args.studentId:
                            raise Unprocessable("Feedback role returned a different student")
                        proposal = _proposal(draft)
                        proposal.feedback = [
                            *[f for f in proposal.feedback if f.studentId != args.studentId],
                            result.feedback,
                        ]
                        nxt = records.append_draft(
                            session_id,
                            proposal,
                            "model",
                            "Individual feedback draft",
                            draft.version,
                        )
                        progress.latestDraftId = nxt.id
                        output = {
                            "draftId": nxt.id,
                            "feedbackStudentId": args.studentId,
                            "auditIssues": [i.model_dump() for i in nxt.content.audit.issues],
                        }
                elif call.name == "request_professor_review":
                    args = _arguments(Review, raw)
                    action["arguments"] = args.model_dump_json()
                    if draft is None:
                        raise Unprocessable("No provisional draft exists")
                    # Say exactly what is missing: a vague refusal had the model retry this
                    # call over and over instead of fixing the draft.
                    blocking = [
                        i for i in audit_draft(draft.content, inputs) if i.severity == "blocking"
                    ]
                    problem = None
                    if blocking:
                        problem = "Complete every roster student's outputs first. Blocking: " + (
                            "; ".join(i.detail for i in blocking[:5])
                        )
                    elif not draft.content.audit.modelReviewed:
                        problem = (
                            f"Draft version {draft.version} changed after its last audit: call "
                            "audit_assessment on it, then request review"
                        )
                    if problem and review_refusals + 1 < MAX_REVIEW_REFUSALS:
                        review_refusals += 1
                        raise Unprocessable(problem)
                    if problem:
                        # Retrying the same refused request only spends the budget: hand the
                        # draft to the professor with its open issues instead. Approval still
                        # refuses a draft with blocking issues, so nothing incomplete is sent.
                        action["outcome"] = "ok"
                        action["summary"] = (
                            f"Escalated to the professor after {MAX_REVIEW_REFUSALS} refused "
                            f"review requests, with open issues. {problem}"
                        )[:600]
                        stop_reason = "escalated_with_open_issues"
                        finished = True
                        output = None
                    else:
                        action["outcome"] = "ok"
                        action["summary"] = (
                            "Complete provisional outputs escalated to professor; no approval or "
                            "delivery performed"
                        )
                        stop_reason = "ready_for_professor_review"
                        finished = True
                        output = None
                else:
                    raise Unprocessable("Unsupported coordinator action")
                if not finished:
                    if len(json.dumps(output, default=str)) > WORKFLOW_LIMITS["historyBytes"] / 2:
                        raise BudgetExceeded()
                    action["outcome"] = "ok"
                    action["summary"] = (
                        "Action completed; inspect the returned result before choosing the next "
                        "action"
                    )
            except BudgetExceeded:
                raise
            except (Unprocessable, ValidationError, ValueError, RuntimeError) as error:
                action["outcome"] = "invalid"
                action["summary"] = (
                    f"Refused: {error}"[:300]
                    if isinstance(error, Unprocessable)
                    else "Action refused or role output invalid; revise the request, inspect "
                    "context or escalate"
                )
                output = {
                    "error": str(error) if isinstance(error, Unprocessable) else action["summary"]
                }
            action["result"] = output
            failure = output.get("error") if isinstance(output, dict) else None
            ledger.record_step(
                step_started,
                action["tool"],
                "ok" if action["outcome"] == "ok" else "refused",
                {"arguments": action["arguments"], "summary": action["summary"], "error": failure}
                if failure
                else {"arguments": action["arguments"], "summary": action["summary"]},
            )
            checkpoint()
            emit("action", action)
            if finished:
                break
            history.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps({"untrustedToolResult": output}, default=str),
                }
            )
    except BudgetExceeded:
        stop_reason = "shared_budget_or_interruption"
    except Exception as error:
        stop_reason = "provider_failure"
        ledger.record_error("coordinator", error)  # the reason, which the run record drops
    progress.elapsedSeconds = round(time.monotonic() - started, 3)
    records.update_run(
        run_id,
        asdict(progress),
        "failed" if stop_reason == "provider_failure" else "needs_review",
        stop_reason,
    )
    emit("done", {"stopReason": stop_reason})
    return run_id


MAX_REVIEW_REFUSALS = 3  # the third refused request_professor_review escalates instead


def _arguments(model: type[Strict], raw) -> Strict:
    """A tool call's arguments, or a refusal that says which field is wrong, so the model can
    correct the call rather than repeat it."""
    try:
        return model.model_validate(raw)
    except ValidationError as error:
        problems = "; ".join(
            f"{'.'.join(str(part) for part in e['loc']) or 'arguments'}: {e['msg']}"
            for e in error.errors()[:3]
        )
        raise Unprocessable(f"Invalid arguments ({problems})") from None


def _proposal(draft: Draft) -> Proposal:
    return Proposal(findings=draft.content.findings, feedback=draft.content.feedback)
