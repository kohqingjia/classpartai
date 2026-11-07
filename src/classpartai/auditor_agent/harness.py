"""Auditor harness: tool menu, validation, execution loop, memory and shared budgets."""

from __future__ import annotations

import contextvars
import hashlib
import json
import time
from collections.abc import Callable
from copy import deepcopy
from dataclasses import asdict, dataclass
from queue import Empty, Queue
from threading import Thread
from typing import TYPE_CHECKING, Any, Protocol

from .contracts import (
    AuditRequest,
    AuditResult,
    AuditState,
    ContractError,
    Issue,
    RejudgeRequest,
    array,
    ids,
    input_fingerprint,
    integer,
    obj,
    text,
    validate_issues,
)

if TYPE_CHECKING:
    from .tools import EvidenceReader


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict


class Model(Protocol):
    def choose(self, messages: list[dict], tools: list[dict], *, timeout: float) -> ToolCall:
        """Return one native tool call; never execute tools inside the adapter."""


@dataclass(frozen=True)
class Limits:
    model_calls: int = 16
    steps: int = 12
    seconds: float = 30.0

    def __post_init__(self) -> None:
        integer(self.model_calls, 1, 40)
        integer(self.steps, 1, 30)
        if not isinstance(self.seconds, (int, float)) or not 0 < self.seconds <= 120:
            raise ContractError("Elapsed time budget outside permitted range")


class BudgetExhausted(RuntimeError):
    pass


class ProviderFailure(RuntimeError):
    """A safe diagnostic; never retains raw provider bodies, headers or request contents."""

    def __init__(self, provider: str, diagnostic: dict):
        super().__init__("Model provider request failed")
        self.diagnostic = {"provider": provider, **diagnostic}


class ToolResponseError(ContractError):
    """A malformed native response, with a safe reason for bounded model correction."""

    def __init__(self, reason: str):
        super().__init__("Model did not return a valid native tool response")
        self.diagnostic = {
            "http_status": None,
            "error_category": "invalid_tool_response",
            "request_issue": reason,
        }


class ToolArgumentError(ContractError):
    def __init__(self, feedback: dict):
        super().__init__("Tool arguments do not match the declared schema")
        self.feedback = feedback


def validate_tool_arguments(value: Any, schema: dict, path: tuple = ()) -> None:
    """Validate the JSON Schema subset used by our tools, including provider-omitted bounds.

    Feedback contains only schema field paths, types, limits and enum values, never rejected
    argument values, unknown field names, evidence text or credentials.
    """

    def refuse(reason: str, **details) -> None:
        raise ToolArgumentError({"reason": reason, "path": list(path), **details})

    expected = schema.get("type")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
    }
    if expected not in valid or not valid[expected]:
        refuse("wrong_type", expected_type=expected)
    if "enum" in schema and value not in schema["enum"]:
        refuse("invalid_enum", allowed_values=schema["enum"])
    if expected == "object":
        properties = schema["properties"]
        missing = sorted(set(schema.get("required", [])) - set(value))
        if missing:
            refuse("missing_required_arguments", missing_fields=missing)
        extra = set(value) - set(properties)
        if extra and schema.get("additionalProperties") is False:
            refuse("unexpected_arguments", unexpected_argument_count=len(extra))
        for key, child in properties.items():
            if key in value:
                validate_tool_arguments(value[key], child, (*path, key))
    elif expected in {"string", "array"}:
        suffix = "Length" if expected == "string" else "Items"
        lower, upper = schema.get("min" + suffix, 0), schema.get("max" + suffix)
        if len(value) < lower or (upper is not None and len(value) > upper):
            refuse("length_out_of_range", minimum=lower, maximum=upper)
        if expected == "array":
            if schema.get("uniqueItems"):
                try:
                    encoded = [json.dumps(item, sort_keys=True, allow_nan=False) for item in value]
                except (ValueError, TypeError):
                    refuse("non_json_argument")
                if len(set(encoded)) != len(encoded):
                    refuse("duplicate_items")
            for index, item in enumerate(value):
                validate_tool_arguments(item, schema["items"], (*path, index))
    elif expected == "integer":
        if value < schema.get("minimum", value) or value > schema.get("maximum", value):
            refuse(
                "number_out_of_range", minimum=schema.get("minimum"), maximum=schema.get("maximum")
            )


def safe_provider_diagnostic(error: Exception) -> dict:
    status = getattr(error, "status_code", None)
    status = status if type(status) is int and 100 <= status <= 599 else None
    body = getattr(error, "body", None)
    detail = body.get("error", body) if isinstance(body, dict) else {}
    code = detail.get("code") if isinstance(detail, dict) else None
    categories = {
        "model_not_found": "model_not_found",
        "model_decommissioned": "model_unavailable",
        "invalid_api_key": "authentication_failed",
        "rate_limit_exceeded": "rate_limit",
        "tool_use_failed": "tool_generation_failed",
        "model_permission_blocked": "permission_denied",
    }
    category = categories.get(code) if isinstance(code, str) else None
    if category is None:
        category = {
            400: "invalid_request",
            401: "authentication_failed",
            403: "permission_denied",
            404: "not_found",
            413: "request_too_large",
            422: "invalid_response",
            429: "rate_limit",
        }.get(status)
    if category is None:
        category = "provider_server_error" if status and status >= 500 else "provider_failure"
    if type(error).__name__ == "APITimeoutError":
        category = "timeout"
    elif type(error).__name__ == "APIConnectionError":
        category = "connection_failure"
    diagnostic = {"http_status": status, "error_category": category}
    if isinstance(code, str) and code in categories:
        diagnostic["provider_code"] = code
    # Describe known provider validation failures using fixed labels, never raw text.
    if status == 400 and isinstance(detail, dict):
        message = detail.get("message")
        message = message.lower() if isinstance(message, str) else ""
        if "invalid json schema" in message or "invalid schema for" in message:
            diagnostic["request_issue"] = "invalid_tool_schema"
            diagnostic["error_category"] = "invalid_request"
            if "uniqueitems" in message:
                diagnostic["schema_keyword"] = "uniqueItems"
            elif "properties" in message and "required" in message:
                diagnostic["schema_keyword"] = "required_properties"
        elif "not in request.tools" in message or "was not in request.tools" in message:
            diagnostic["request_issue"] = "unknown_generated_tool"
            diagnostic["error_category"] = "tool_generation_failed"
        elif (
            "tool" in message
            and "required" in message
            and ("did not call" in message or "did not generate" in message)
        ):
            diagnostic["request_issue"] = "required_tool_call_missing"
            diagnostic["error_category"] = "tool_generation_failed"
        elif "failed to parse tool" in message or "failed to parse function" in message:
            diagnostic["request_issue"] = "generated_arguments_invalid_json"
            diagnostic["error_category"] = "tool_generation_failed"
        if isinstance(code, str) and code in {"invalid_request_error", "json_validate_failed"}:
            diagnostic["provider_code"] = code
    # Only numeric Retry-After is exposed; no raw headers, error text or generated content.
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", {})
    value = headers.get("retry-after") if hasattr(headers, "get") else None
    if isinstance(value, str) and len(value) <= 20:
        try:
            seconds = float(value)
            if 0 <= seconds <= 86400:
                diagnostic["retry_after_seconds"] = seconds
        except ValueError:
            pass
    return diagnostic


def bounded_call(fn: Callable[[], Any], timeout: float) -> Any:
    """Do not wait indefinitely for a provider/reader that ignores its timeout.

    Python cannot kill a thread safely. A timed-out daemon may finish its read later, but no
    late result is consumed and the adapter is never given permission to execute audit tools.
    """
    queue: Queue = Queue(maxsize=1)

    def run() -> None:
        try:
            queue.put((True, fn()))
        except Exception as exc:
            queue.put((False, exc))

    # The thread starts with the caller's context, so the usage ledger still knows which run
    # and agent a model call made in it belongs to.
    Thread(target=contextvars.copy_context().run, args=(run,), daemon=True).start()
    try:
        ok, result = queue.get(timeout=max(0.001, timeout))
    except Empty as exc:
        raise BudgetExhausted("Elapsed time exhausted") from exc
    if not ok:
        raise result
    return result


class Budget:
    def __init__(self, limits: Limits):
        self.limits = limits
        self.started = time.monotonic()
        self.calls = 0
        self.steps = 0
        self.events: list[dict] = []
        self.tool_repairs = 0

    def remaining(self) -> float:
        left = self.limits.seconds - (time.monotonic() - self.started)
        if left <= 0:
            raise BudgetExhausted("Elapsed time exhausted")
        return left

    def choose(self, model: Model, messages: list[dict], tools: list[dict]) -> ToolCall:
        while True:
            remaining = self.remaining()
            if len(json.dumps(messages).encode()) > 250000:
                raise BudgetExhausted("Working memory budget exhausted")
            if self.calls >= self.limits.model_calls:
                raise BudgetExhausted("Model call budget exhausted")
            self.calls += 1
            started = time.monotonic()
            failure = None
            try:
                result = bounded_call(
                    lambda remaining=remaining: model.choose(messages, tools, timeout=remaining),
                    remaining,
                )
            except (ProviderFailure, ToolResponseError) as error:
                failure = error
            finally:
                self.events.append(
                    {
                        "kind": "model_call",
                        "allowed_tools": [t["function"]["name"] for t in tools],
                        "latency_ms": round((time.monotonic() - started) * 1000, 3),
                    }
                )
            self.remaining()
            if failure is not None:
                repairable = (
                    (
                        isinstance(failure, ToolResponseError)
                        or (
                            failure.diagnostic.get("http_status") == 400
                            and failure.diagnostic.get("error_category") == "tool_generation_failed"
                        )
                    )
                    and self.tool_repairs < 1
                    and self.calls < self.limits.model_calls
                )
                if not repairable:
                    raise failure
                self.tool_repairs += 1
                self.events.append(
                    {
                        "kind": "model_response_error"
                        if isinstance(failure, ToolResponseError)
                        else "provider_error",
                        **failure.diagnostic,
                        "recovery": "tool_schema_feedback",
                    }
                )
                # A rejected provider generation is never parsed into an executable tool call.
                # Use a trusted user message, since no accepted assistant tool-call ID exists.
                messages.append(
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "backend_feedback": "tool_call_rejected",
                                "instruction": (
                                    "Choose exactly one native function "
                                    "tool. Use its exact name without "
                                    "prefixes and supply every required "
                                    "argument with the declared JSON types."
                                    " Do not invent IDs, scores, approvals "
                                    "or permissions. Inspect the prior "
                                    "results before choosing your action."
                                ),
                                "allowed_calls": [
                                    {
                                        "name": t["function"]["name"],
                                        "required_arguments": t["function"]["parameters"].get(
                                            "required", []
                                        ),
                                        "argument_types": {
                                            key: value["type"]
                                            for key, value in t["function"]["parameters"]
                                            .get("properties", {})
                                            .items()
                                        },
                                    }
                                    for t in tools
                                ],
                            }
                        ),
                    }
                )
                continue
            if not isinstance(result, ToolCall):
                raise ContractError("Provider must return a typed native tool call")
            text(result.call_id, 100)
            text(result.name, 100)
            obj(
                result.arguments,
                set(result.arguments) if isinstance(result.arguments, dict) else set(),
            )
            return result

    def step(self) -> None:
        self.remaining()
        if self.steps >= self.limits.steps:
            raise BudgetExhausted("Tool step budget exhausted")
        self.steps += 1


def definition(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


ID = {"type": "string", "minLength": 1, "maxLength": 100}
ID_LIST = {"type": "array", "items": ID, "maxItems": 60, "uniqueItems": True}
ISSUE_JSON = {
    "type": "object",
    "additionalProperties": False,
    "required": ["issue_id", "kind", "severity", "finding_ids", "evidence_ids", "objection"],
    "properties": {
        "issue_id": ID,
        "kind": {
            "type": "string",
            "enum": [
                "citation",
                "consistency",
                "injection",
                "attribution",
                "fairness",
                "rationale",
                "missing_evidence",
                "execution",
            ],
        },
        "severity": {"type": "string", "enum": ["material", "review"]},
        "finding_ids": ID_LIST,
        "evidence_ids": ID_LIST,
        "objection": {"type": "string", "minLength": 1, "maxLength": 2000},
    },
}
BASE_COMPARE_DESCRIPTION = (
    "Lexical comparisons under the exact same rubric; differences require "
    "investigation, never equalisation"
)
COMPARE_DESCRIPTION = (
    "Use when findings under the same rubric criterion appear inconsistent. "
    "Returns lexically similar contributions for comparison. Check context "
    "and rubric descriptors before flagging a score difference."
)


@dataclass(frozen=True)
class AuditTuning:
    """Trusted caller-only experiment controls; none can bypass a safety check.

    Defaults enable the revised behaviour. Baseline values reproduce the previous wording,
    terminal early-pass behaviour and score-policy wording for controlled comparisons.
    """

    comparison_cue: bool = True
    recover_missing_checks: bool = True
    score_policy: bool = True


TOOLS = [
    definition(
        "get_session_scores",
        (
            "Use when you need to inspect Judge findings or rationales, "
            "including before making an objection. Read scoped pages of at "
            "most ten findings; offset selects the next page."
        ),
        {
            "offset": {"type": "integer", "minimum": 0, "maximum": 59},
            "limit": {"type": "integer", "minimum": 1, "maximum": 10},
        },
        ["offset", "limit"],
    ),
    definition(
        "compare_similar",
        COMPARE_DESCRIPTION,
        {"finding_id": ID, "k": {"type": "integer", "minimum": 1, "maximum": 5}},
        ["finding_id", "k"],
    ),
    definition(
        "verify_citation",
        (
            "Use when a finding cites course evidence or source support is "
            "unclear. Fetch only an evidence ID attached to that finding. "
            "Validate the reference and quotation separately from "
            "model-assessed support; this does not validate the score."
        ),
        {"finding_id": ID, "evidence_id": ID},
        ["finding_id", "evidence_id"],
    ),
    definition(
        "score_stats",
        (
            "Use when multiple scored contributions and speaking-duration"
            " metadata warrant a fairness check. Skip if not useful. Report"
            " sample size and missingness; correlation is not proven bias "
            "and text does not establish loudness."
        ),
        {},
        [],
    ),
    definition(
        "request_rejudge",
        (
            "Use for a specific material objection after inspecting "
            "affected findings and any cited evidence. Request one targeted"
            " Judge revision only; if the round is already used, escalate. "
            "Never provide a replacement grade or send messages."
        ),
        {"issues": {"type": "array", "items": ISSUE_JSON, "minItems": 1, "maxItems": 20}},
        ["issues"],
    ),
    definition(
        "complete_audit",
        (
            "Use when you can finish after observing required findings and "
            "citations. Include "
            "resolved_issue_ids as a list (empty for the first audit). "
            "Missing checks block pass and return actionable feedback."
        ),
        {
            "verdict": {"type": "string", "enum": ["audit_passed", "professor_review_required"]},
            "issues": {"type": "array", "items": ISSUE_JSON, "maxItems": 20},
            "resolved_issue_ids": ID_LIST,
        },
        ["verdict", "issues", "resolved_issue_ids"],
    ),
]
CITATION_TOOL = definition(
    "citation_assessment",
    "Assess support of the exact rationale, not the student's grade",
    {
        "relationship": {
            "type": "string",
            "enum": ["supports", "partly_supports", "contradicts", "fails_to_verify"],
        },
        "quote": {"type": "string", "maxLength": 4000},
        "explanation": {"type": "string", "minLength": 1, "maxLength": 1500},
    },
    ["relationship", "quote", "explanation"],
)


def run_audit(
    request: dict,
    *,
    model: Model | None,
    evidence_reader: EvidenceReader,
    limits: Limits | None = None,
    tuning: AuditTuning | None = None,
    prompt: str,
    allow_rejudge: bool = True,
) -> AuditResult:
    """Accept JSON-compatible input with authenticated scope and trusted persisted state.

    ContractError rejects invalid input before model execution. No files or application records
    are written. The result carries the in-memory trace. Persist state atomically in the caller.
    """
    from .tools import AuditTools, keep_prior_objections, merge_issues, refuse_reused_ids

    req = AuditRequest.parse(request)
    budget = Budget(limits or Limits())
    tuning = tuning or AuditTuning()
    available_tools = [
        t for t in deepcopy(TOOLS) if allow_rejudge or t["function"]["name"] != "request_rejudge"
    ]
    if not tuning.comparison_cue:
        next(t for t in available_tools if t["function"]["name"] == "compare_similar")["function"][
            "description"
        ] = BASE_COMPARE_DESCRIPTION
    trace_id = (
        "trace-"
        + hashlib.sha256(
            (json.dumps(request, sort_keys=True) + str(time.monotonic_ns())).encode()
        ).hexdigest()[:24]
    )
    tools = AuditTools(req, model, evidence_reader, budget)
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "untrusted_data": {
                        # Most stable first and the case id last: a model reuses a prompt's
                        # unchanged opening, so a re-audit of the same session shares it.
                        "rubric": asdict(req.rubric),
                        "contributions": [
                            {
                                key: value
                                for key, value in asdict(c).items()
                                if key != "transcription_confidence"
                            }
                            for c in req.contributions
                        ],
                        "finding_ids": [f.finding_id for f in req.proposal.findings],
                        "pending_objections": asdict(req.state.pending_rejudge)
                        if req.state.pending_rejudge
                        else None,
                        "case_id": req.audit_case_id,
                    }
                }
            ),
        },
    ]
    terminal_issues: list[Issue] = []
    rejudge: RejudgeRequest | None = None
    verdict = "professor_review_required"
    stop = "configuration_blocked"
    used_call_ids: set[str] = set()
    prior_objections = req.state.pending_rejudge.objections if req.state.pending_rejudge else []
    if model is None:
        terminal_issues = [
            execution_issue(
                "Model configuration missing; set the selected provider"
                " key (OPENAI_API_KEY or GROQ_API_KEY), or configure "
                "local mode"
            )
        ]
    else:
        try:
            while True:
                if len(json.dumps(messages).encode()) > 250000:
                    raise BudgetExhausted("Working memory budget exhausted")
                call = budget.choose(model, messages, available_tools)
                budget.step()
                started = time.monotonic()
                allowed = {t["function"]["name"] for t in available_tools}
                action = {
                    "kind": "tool",
                    "tool": call.name if call.name in allowed else "disallowed",
                    "arguments": {},
                    "result_references": [],
                    "outcome": "invalid",
                    "latency_ms": 0.0,
                }
                try:
                    if call.name not in allowed:
                        raise ToolArgumentError(
                            {
                                "reason": "unknown_tool_name",
                                "path": [],
                                "allowed_tools": sorted(allowed),
                            }
                        )
                    if call.call_id in used_call_ids:
                        raise ToolArgumentError({"reason": "replayed_call_id", "path": []})
                    used_call_ids.add(call.call_id)
                    args = call.arguments
                    definition = next(
                        t["function"] for t in available_tools if t["function"]["name"] == call.name
                    )
                    validate_tool_arguments(args, definition["parameters"])
                    action["arguments"] = safe_args(args)
                    if call.name == "request_rejudge":
                        if req.state.rejudge_count == 1:
                            parsed = parse_issues(args["issues"], req)
                            refuse_reused_ids(parsed, prior_objections)
                            terminal_issues = merge_issues(parsed, tools.issues)
                            if not terminal_issues:
                                terminal_issues = [
                                    execution_issue(
                                        "Rejudge round already used; no second handoff permitted"
                                    )
                                ]
                            stop = "one_rejudge_limit"
                        else:
                            rejudge = tools.request_rejudge(**args)
                            terminal_issues = rejudge.objections
                            verdict = "rejudge_requested"
                            stop = "targeted_rejudge"
                        action["outcome"] = "ok"
                        break
                    if call.name == "complete_audit":
                        parsed = parse_issues(args["issues"], req)
                        refuse_reused_ids(parsed, prior_objections)
                        terminal_issues = merge_issues(parsed, tools.issues)
                        if args["verdict"] not in ("audit_passed", "professor_review_required"):
                            raise ContractError("Unknown proposed verdict")
                        resolved = ids(args["resolved_issue_ids"])
                        pending = (
                            {i.issue_id for i in req.state.pending_rejudge.objections}
                            if req.state.pending_rejudge
                            else set()
                        )
                        if not set(resolved) <= pending:
                            raise ContractError("Cannot resolve unknown prior objections")
                        gaps = tools.pass_gaps()
                        if args["verdict"] == "audit_passed" and pending != set(resolved):
                            gaps.append("Prior objections have not all been addressed explicitly")
                        missing = tools.missing_checks()
                        recoverable = set()
                        if missing["finding_ids"]:
                            recoverable.add("Not all findings were inspected")
                        if missing["citations"]:
                            recoverable.add("A citation remains invalid, unverified or unsupported")
                        can_recover = (
                            tuning.recover_missing_checks
                            and args["verdict"] == "audit_passed"
                            and not terminal_issues
                            and bool(recoverable)
                            and set(gaps) <= recoverable
                            and budget.calls < budget.limits.model_calls
                            and budget.steps < budget.limits.steps
                        )
                        budget.remaining()
                        if can_recover:
                            output = {
                                "status": "pass_blocked",
                                "missing_checks": missing,
                                "message": (
                                    "Required checks are incomplete. "
                                    "Inspect the listed findings and verify"
                                    " the listed citations, observe the "
                                    "results, then choose whether to "
                                    "finish, rejudge or escalate."
                                ),
                            }
                            action["outcome"] = "pass_blocked"
                            action["result_references"] = sorted(
                                set(missing["finding_ids"])
                                | {ref["evidence_id"] for ref in missing["citations"]}
                            )
                        else:
                            if (
                                args["verdict"] == "audit_passed"
                                and not terminal_issues
                                and not gaps
                            ):
                                verdict, stop = "audit_passed", "model_completed_validated"
                            else:
                                terminal_issues = merge_issues(
                                    terminal_issues, [execution_issue(g) for g in gaps]
                                )
                                if not terminal_issues:
                                    terminal_issues = [
                                        execution_issue("Model requested professor judgement")
                                    ]
                                stop = "unresolved_audit_issues"
                            action["outcome"] = "ok"
                            break
                    else:
                        output = getattr(tools, call.name)(**args)
                        budget.remaining()
                        action["outcome"] = "ok"
                        action["result_references"] = result_refs(output)
                except ContractError as error:
                    if isinstance(error, ToolArgumentError):
                        output = {
                            "status": "tool_call_invalid",
                            "validation": error.feedback,
                            "instruction": (
                                "Correct the listed arguments or choose "
                                "another allowed investigation; use only "
                                "observed authorised IDs."
                            ),
                        }
                        action["validation"] = error.feedback
                    else:
                        reasons = {
                            "Finding is not in the trusted session proposal": "unknown_finding",
                            "Evidence reference does not belong to finding": "wrong_citation",
                            "Unknown contribution": "contribution_not_in_session",
                            "Inspect affected findings before objecting": "inspect_first",
                            "Verify cited evidence before objecting": "verify_first",
                            "Issue references unknown findings or evidence": "unknown_refs",
                            "Cannot resolve unknown prior objections": "unknown_prior_issue",
                            "Issue ID reused for a different objection": "issue_id_reused",
                        }
                        reason = reasons.get(str(error), "invalid_reference_state_or_result")
                        output = {
                            "status": "tool_refused",
                            "reason": reason,
                            "instruction": (
                                "Use IDs from the authorised inputs or "
                                "prior tool results. Inspect missing "
                                "context, revise the request, or escalate "
                                "if unresolved."
                            ),
                        }
                finally:
                    action["latency_ms"] = round((time.monotonic() - started) * 1000, 3)
                    budget.events.append(action)
                messages.extend(
                    [
                        {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": call.call_id,
                                    "type": "function",
                                    "function": {
                                        "name": call.name,
                                        "arguments": json.dumps(call.arguments),
                                    },
                                }
                            ],
                        },
                        {
                            "role": "tool",
                            "tool_call_id": call.call_id,
                            "content": json.dumps({"untrusted_tool_result": output}),
                        },
                    ]
                )
        except BudgetExhausted:
            stop = "budget_exhausted"
            terminal_issues = merge_issues(
                tools.issues,
                [execution_issue("Audit budget exhausted before a defensible conclusion")],
            )
        except Exception as error:
            # Record allowlisted diagnostics, never provider error bodies or secrets.
            if isinstance(error, (ProviderFailure, ToolResponseError)):
                budget.events.append(
                    {
                        "kind": "model_response_error"
                        if isinstance(error, ToolResponseError)
                        else "provider_error",
                        **error.diagnostic,
                    }
                )
            stop = "provider_or_reader_failure"
            terminal_issues = merge_issues(
                tools.issues,
                [execution_issue("Model or evidence adapter failed; audit cannot pass")],
            )
    if req.state.rejudge_count == 1 and verdict != "audit_passed":
        # Preserve the original targeted objections when the return is inconclusive/failed.
        # Never overwrite an original objection, and never raise outside the guarded loop.
        terminal_issues = keep_prior_objections(terminal_issues, prior_objections)
    new_state = AuditState(
        1,
        req.audit_case_id,
        req.trusted_scope,
        req.rubric.rubric_id,
        req.rubric.version,
        req.state.state_version + 1,
        1 if rejudge else req.state.rejudge_count,
        req.proposal.reference,
        rejudge,
        verdict != "rejudge_requested",
        input_fingerprint(req),
        {f.finding_id: [f.contribution_id, f.criterion_id] for f in req.proposal.findings},
    )
    result = AuditResult(
        1,
        req.audit_case_id,
        req.proposal.reference,
        verdict,
        terminal_issues,
        sorted({f for i in terminal_issues for f in i.finding_ids}),
        sorted(
            {e for i in terminal_issues for e in i.evidence_ids}
            | {key[1] for key in tools.verified}
        ),
        trace_id,
        stop,
        new_state,
        rejudge,
        budget.events,
        {
            "model_calls": budget.calls,
            "tool_steps": budget.steps,
            "elapsed_ms": round((time.monotonic() - budget.started) * 1000, 3),
            "tokens": None,
            "token_accounting": "not_reported_by_interface",
        },
    )
    # Validate serialised output against its public versioned contract, too.
    return AuditResult.parse(result.to_dict())


def parse_issues(data: list[dict], request: AuditRequest) -> list[Issue]:
    issues = [Issue.parse(i) for i in array(data, 20)]
    validate_issues(issues, request)
    return issues


def execution_issue(message: str) -> Issue:
    digest = hashlib.sha256(message.encode()).hexdigest()[:16]
    return Issue("execution-" + digest, "execution", "review", [], [], message)


def safe_args(args: dict) -> dict:
    # Do not log arbitrary strings, rationales, transcript text, raw malformed arguments or secrets.
    result = {}
    for key in (
        "finding_id",
        "evidence_id",
        "target_id",
        "target",
        "offset",
        "limit",
        "k",
        "verdict",
    ):
        value = args.get(key)
        if isinstance(value, int) and not isinstance(value, bool):
            result[key] = value
        elif (
            isinstance(value, str)
            and len(value) <= 100
            and all(c.isascii() and (c.isalnum() or c in "-_.:") for c in value)
        ):
            result[key] = value
    if isinstance(args.get("issues"), list):
        result["issue_count"] = len(args["issues"])
    return result


def result_refs(output: dict) -> list[str]:
    refs = []
    if "evidence_id" in output:
        refs.append(output["evidence_id"])
    refs.extend(f["finding_id"] for f in output.get("findings", []))
    refs.extend(f["finding_id"] for f in output.get("matches", []))
    return refs
