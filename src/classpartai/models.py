"""Model drivers and the shared workflow budget.

Ported from Le Yong's src/features/models/local.server.ts and budget.ts. The original only
allowed a free local model (and shipped with it switched off); this port talks to any
OpenAI-compatible chat-completions endpoint: OpenAI by default, or a local server such as
Ollama via OPENAI_BASE_URL. The request shape and the one-tool-call-per-turn protocol are
unchanged.
"""

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel

from classpartai import config
from classpartai import usage as ledger

HistoryItem = dict[str, Any]


@dataclass
class ModelCall:
    name: str
    call_id: str
    arguments: str


@dataclass
class ModelTurn:
    calls: list[ModelCall]
    tokens: int
    usage_kind: str = "reported"  # or "estimated"


class Driver(Protocol):
    def estimate_tokens(self, history: list[HistoryItem]) -> int: ...
    def next(self, history: list[HistoryItem]) -> ModelTurn: ...


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict


def tool(name: str, description: str, schema: type[BaseModel]) -> ToolDefinition:
    return ToolDefinition(name, description, schema.model_json_schema())


def to_messages(instructions: str, history: list[HistoryItem]) -> list[dict]:
    """Convert the agents' history items into chat-completions messages."""
    messages: list[dict] = [{"role": "system", "content": instructions}]
    for item in history:
        if item.get("type") == "function_call":
            messages.append(
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": item["call_id"],
                            "type": "function",
                            "function": {"name": item["name"], "arguments": item["arguments"]},
                        }
                    ],
                }
            )
        elif item.get("type") == "function_call_output":
            messages.append(
                {"role": "tool", "tool_call_id": item["call_id"], "content": item["output"]}
            )
        else:
            messages.append(item)
    return messages


class OpenAIDriver:
    """One structured tool call per turn from an OpenAI-compatible endpoint."""

    def __init__(
        self,
        instructions: str,
        tools: list[ToolDefinition],
        model: str,
        client,
        provider: str = "openai",
    ):
        self.instructions = instructions
        self.provider = provider
        self.tools = [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]
        self.model = model
        self.client = client

    def estimate_tokens(self, history: list[HistoryItem]) -> int:
        # Same rough bound as the original: payload bytes plus the output allowance.
        payload = json.dumps(to_messages(self.instructions, history)) + json.dumps(self.tools)
        return len(payload.encode()) // 4 + 4000

    def next(self, history: list[HistoryItem]) -> ModelTurn:
        kwargs: dict = {
            "model": self.model,
            "messages": to_messages(self.instructions, history),
            "tools": self.tools,
            "tool_choice": "required",
            "parallel_tool_calls": False,
        }
        # A thinking level per agent (config.REASONING_EFFORT). Only OpenAI's own models are
        # given one unprompted: a local or compatible endpoint may not accept the setting.
        agent = ledger.current().get("agent")
        effort = config.REASONING_EFFORT.get(agent)
        if effort and (self.provider == "openai" or agent == "judge"):
            kwargs["reasoning_effort"] = effort
        if self.provider == "openai" and ledger.cache_key():
            kwargs["prompt_cache_key"] = ledger.cache_key()
        started = ledger.begin()
        try:
            response = self.client.chat.completions.create(**kwargs)
        except Exception as error:
            ledger.record_model_call(
                started,
                model=self.model,
                provider=self.provider,
                status="error",
                error=f"{type(error).__name__}: {error}",
            )
            raise
        message = response.choices[0].message
        calls = [
            ModelCall(c.function.name, c.id, c.function.arguments)
            for c in (message.tool_calls or [])
        ]
        usage = getattr(response, "usage", None)
        ledger.record_model_call(
            started,
            model=self.model,
            provider=self.provider,
            usage=usage,
            calls=[c.name for c in calls],
            input=kwargs["messages"][-1].get("content") if kwargs["messages"] else None,
            output=message.content or [f"{c.name}({c.arguments})" for c in calls],
        )
        if usage and usage.total_tokens is not None:
            return ModelTurn(calls, usage.total_tokens, "reported")
        return ModelTurn(calls, self.estimate_tokens(history), "estimated")


def configured_driver(instructions: str, tools: list[ToolDefinition]) -> Driver | None:
    """The app's driver, or None when no model is configured (runs are then 'blocked')."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from openai import OpenAI

    base_url = os.getenv("OPENAI_BASE_URL") or None
    client = OpenAI(base_url=base_url, timeout=60)
    # A local server (Ollama, ...) costs nothing; another hosted endpoint is priced by model name.
    provider = "openai"
    if base_url:
        local = any(host in base_url for host in ("localhost", "127.0.0.1", "host.docker.internal"))
        provider = "local" if local else "compatible"
    return OpenAIDriver(
        instructions, tools, os.getenv("OPENAI_MODEL", "gpt-5-mini"), client, provider
    )


# --- Shared budget ----------------------------------------------------------------------------

# Original limits were 24 model calls, 36 tool calls, 100k tokens and 120 s for a local model.
# A real run needs a feedback call per student plus judge, audit and evidence calls, and OpenAI
# reasoning models count hidden reasoning tokens and add latency, so all four are raised here.
# One Research investigation (research/bridge.py) alone takes about 25 model calls and 2 minutes.
WORKFLOW_LIMITS = {
    # 96 since 2026-11-08: Research checks two answers per call at about ten model calls each,
    # so a four-student seminar where everyone makes a course claim used 43 calls on Research
    # alone, and 72 left too little for the audit after feedback (Demo 1, run de6e4abc).
    "modelCalls": 96,
    "toolCalls": 108,
    "tokens": 500000,
    "seconds": 900,
    "historyBytes": 100000,
}


class BudgetExceeded(Exception):
    def __init__(self) -> None:
        super().__init__("Shared workflow budget or deadline exhausted")


@dataclass
class WorkflowProgress:
    modelCalls: int = 0
    toolCalls: int = 0
    tokens: int = 0
    usageKind: str = "reported"
    actions: list[dict] = field(default_factory=list)
    roleCalls: list[dict] = field(default_factory=list)
    coordinatorInput: dict = field(default_factory=dict)
    elapsedSeconds: float = 0.0
    latestDraftId: str | None = None
    evidenceRunIds: list[str] = field(default_factory=list)


class SharedBudget:
    """One budget across the coordinator and every role and evidence agent it invokes."""

    def __init__(self, progress: WorkflowProgress, deadline: float, checkpoint=lambda: None):
        self.progress = progress
        self.deadline = deadline
        self.checkpoint = checkpoint

    def expired(self) -> bool:
        return time.monotonic() > self.deadline

    def tool(self, count: int = 1) -> None:
        if self.expired() or self.progress.toolCalls + count > WORKFLOW_LIMITS["toolCalls"]:
            raise BudgetExceeded()
        self.progress.toolCalls += count

    def wrap(self, driver: Driver) -> Driver:
        budget = self

        class Wrapped:
            def estimate_tokens(self, history):
                return driver.estimate_tokens(history)

            def next(self, history):
                return budget.call(driver, history)

        return Wrapped()

    def call(self, driver: Driver, history: list[HistoryItem]) -> ModelTurn:
        if (
            self.expired()
            or self.progress.modelCalls >= WORKFLOW_LIMITS["modelCalls"]
            or self.progress.tokens + driver.estimate_tokens(history) > WORKFLOW_LIMITS["tokens"]
            or len(json.dumps(history).encode()) > WORKFLOW_LIMITS["historyBytes"]
        ):
            raise BudgetExceeded()
        self.progress.modelCalls += 1
        self.checkpoint()
        result = driver.next(history)
        if not isinstance(result.tokens, int) or result.tokens < 0:
            raise RuntimeError("Invalid provider usage")
        self.progress.tokens += result.tokens
        if result.usage_kind == "estimated":
            self.progress.usageKind = "includes_estimates"
        self.checkpoint()
        if self.progress.tokens > WORKFLOW_LIMITS["tokens"]:
            raise BudgetExceeded()
        return result
