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

    def __init__(self, instructions: str, tools: list[ToolDefinition], model: str, client):
        self.instructions = instructions
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
        response = self.client.chat.completions.create(
            model=self.model,
            messages=to_messages(self.instructions, history),
            tools=self.tools,
            tool_choice="required",
            parallel_tool_calls=False,
        )
        message = response.choices[0].message
        calls = [
            ModelCall(c.function.name, c.id, c.function.arguments)
            for c in (message.tool_calls or [])
        ]
        usage = getattr(response, "usage", None)
        if usage and usage.total_tokens is not None:
            return ModelTurn(calls, usage.total_tokens, "reported")
        return ModelTurn(calls, self.estimate_tokens(history), "estimated")


def configured_driver(instructions: str, tools: list[ToolDefinition]) -> Driver | None:
    """The app's driver, or None when no model is configured (runs are then 'blocked')."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    from openai import OpenAI

    client = OpenAI(base_url=os.getenv("OPENAI_BASE_URL") or None, timeout=60)
    return OpenAIDriver(instructions, tools, os.getenv("OPENAI_MODEL", "gpt-5-mini"), client)


# --- Shared budget ----------------------------------------------------------------------------

# Original limits were 100k tokens / 120 s for a local model. OpenAI reasoning models count
# hidden reasoning tokens and add network latency, so tokens and time are raised here.
WORKFLOW_LIMITS = {
    "modelCalls": 24,
    "toolCalls": 36,
    "tokens": 150000,
    "seconds": 300,
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
