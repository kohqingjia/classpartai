"""The participation coordinator agent (ported from participation/coordinator.server.ts).

The coordinator chooses its own route: inspect the transcript, retrieve course evidence (via
the evidence agent), run the judge, audit, revise, draft each student's feedback, and finally
hand everything to the professor. It has no approval or delivery tools.

``on_event(kind, detail)`` lets the UI animate the run: "thinking" before each model call,
"action" after each tool call (detail = the action record), "done" at the end.
"""

import json
import time
from collections.abc import Callable
from dataclasses import asdict

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from classpartai.participation.records import Draft, Records
from classpartai.participation.roles import (
    ROLE_POLICY,
    DriverFactory,
    feedback_for,
    judge,
    model_audit,
)
from classpartai.participation.schema import Proposal
from classpartai.participation.validation import Unprocessable, audit_draft


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
        },
        WORKFLOW_LIMITS["seconds"],
    )

    def checkpoint() -> None:
        records.update_run(run_id, asdict(progress))

    try:
        driver = factory(COORDINATOR_POLICY, COORDINATOR_TOOLS)
    except Exception:
        driver = None
    if driver is None:
        records.update_run(
            run_id, asdict(progress), "configuration_blocked", "model_not_configured"
        )
        on_event("done", {"stopReason": "model_not_configured"})
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
    turns = inputs.transcript.turns
    stop_reason = "shared_budget_exhausted"
    try:
        while True:
            if budget.expired():
                raise BudgetExceeded()
            on_event("thinking", None)
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
                "summary": "Action requested",
                "outcome": "started",
            }
            progress.actions.append(action)
            checkpoint()
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
                    args = Inspect.model_validate(raw)
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
                    args = Retrieve.model_validate(raw)
                    action["arguments"] = args.model_dump_json()
                    if args.reuseRunId:
                        bundle = dict(records.evidence_for(session_id)).get(args.reuseRunId)
                        if bundle is None:
                            raise Unprocessable(
                                "Existing evidence is unavailable for this snapshot"
                            )
                        output = {"id": args.reuseRunId, "bundle": bundle.model_dump()}
                    else:
                        evidence_driver = factory(EVIDENCE_INSTRUCTIONS, EVIDENCE_TOOLS)
                        if evidence_driver is None:
                            raise RuntimeError("Model configuration blocked")
                        request = Investigation(
                            sessionId=session_id,
                            question=args.question,
                            turnIds=args.turnIds,
                            criterionIds=args.criterionIds,
                        )
                        before = 0

                        def count_tools(p):
                            # Evidence-agent tool calls count against the shared budget too.
                            nonlocal before
                            if p.toolCalls > before:
                                budget.tool(p.toolCalls - before)
                                before = p.toolCalls

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
                    args = Revise.model_validate(raw)
                    action["arguments"] = args.model_dump_json()
                    judged = judge(
                        inputs, records.evidence_for(session_id), budget, factory, session_id
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
                    args = Revise.model_validate(raw)
                    action["arguments"] = args.model_dump_json()
                    if draft is None:
                        raise Unprocessable("Create a provisional draft before audit")
                    audit = model_audit(
                        inputs, draft.content, records.evidence_for(session_id), budget, factory
                    )
                    nxt = records.append_draft(
                        session_id, _proposal(draft), "model", args.note, draft.version, audit
                    )
                    progress.latestDraftId = nxt.id
                    output = {"draftId": nxt.id, "audit": nxt.content.audit.model_dump()}
                elif call.name == "draft_student_feedback":
                    args = Student.model_validate(raw)
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
                    args = Review.model_validate(raw)
                    action["arguments"] = args.model_dump_json()
                    if draft is None:
                        raise Unprocessable("No provisional draft exists")
                    if (
                        any(i.severity == "blocking" for i in audit_draft(draft.content, inputs))
                        or not draft.content.audit.modelReviewed
                    ):
                        raise Unprocessable(
                            "Complete every roster student's outputs and audit the current draft "
                            "first"
                        )
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
                    "Action refused or role output invalid; revise the request, inspect context "
                    "or escalate"
                )
                output = {
                    "error": str(error) if isinstance(error, Unprocessable) else action["summary"]
                }
            checkpoint()
            on_event("action", action)
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
    except Exception:
        stop_reason = "provider_failure"
    records.update_run(
        run_id,
        asdict(progress),
        "failed" if stop_reason == "provider_failure" else "needs_review",
        stop_reason,
    )
    on_event("done", {"stopReason": stop_reason})
    return run_id


def _proposal(draft: Draft) -> Proposal:
    return Proposal(findings=draft.content.findings, feedback=draft.content.feedback)
