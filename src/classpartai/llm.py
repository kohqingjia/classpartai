"""Thin wrappers around the chat and embedding APIs (OpenAI, or Ollama locally), shared by
every agent.

Each wrapper sits behind a small Protocol so tests (and other providers) can swap in a stand-in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON text, exactly as the model produced it

    def parsed_arguments(self) -> dict:
        return json.loads(self.arguments or "{}")


@dataclass
class AssistantTurn:
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens: int | None = None  # total tokens the provider reported for the call, if it did

    def as_message(self) -> dict:
        """The turn in plain OpenAI form, to append to the message history."""
        message: dict = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            message["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        return message


class ChatModel(Protocol):
    name: str

    def complete(
        self, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False
    ) -> AssistantTurn: ...


class Embedder(Protocol):
    name: str

    def encode(self, texts: list[str]) -> np.ndarray:
        """One L2-normalised row per text, so a dot product is the cosine similarity."""
        ...


def _settings(provider: str | None) -> tuple[str, str, str]:
    """(provider, chat model, embedding model) from config, for "openai" or "ollama"."""
    from classpartai import config

    provider = (provider or config.LLM_PROVIDER).lower()
    if provider == "ollama":
        return provider, config.OLLAMA_MODEL, config.OLLAMA_EMBEDDING_MODEL
    if provider == "openai":
        return provider, config.OPENAI_MODEL, config.OPENAI_EMBEDDING_MODEL
    raise ValueError(f"LLM_PROVIDER must be 'openai' or 'ollama', not {provider!r}")


def make_client(provider: str):
    """An OpenAI client, pointed at the local Ollama server when the provider is Ollama (Ollama
    serves an OpenAI-compatible API and ignores the key, which the client still requires)."""
    from openai import OpenAI

    if provider == "ollama":
        from classpartai.config import OLLAMA_BASE_URL

        return OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    return OpenAI()


class OpenAIChat:
    """Chat with tool calling through the OpenAI API, or through Ollama's OpenAI-compatible API."""

    def __init__(
        self,
        model: str | None = None,
        client=None,
        max_tokens: int = 4096,
        provider: str | None = None,
        reasoning_effort: str | None = None,
    ):
        from classpartai.config import LLM_REASONING_EFFORT

        self.provider, default_model, _ = _settings(provider)
        self.model = model or default_model
        self.name = f"{self.provider}:{self.model}"
        self.client = client or make_client(self.provider)
        self.max_tokens = max_tokens
        self.reasoning_effort = reasoning_effort or LLM_REASONING_EFFORT

    def complete(
        self, messages: list[dict], tools: list[dict] | None = None, json_mode: bool = False
    ) -> AssistantTurn:
        # No temperature: OpenAI's reasoning models only accept the default. No tool_choice:
        # "auto" is the default whenever tools are given, and Ollama does not accept the field.
        kwargs: dict = {"model": self.model, "messages": messages}
        # OpenAI's newer models need max_completion_tokens; Ollama only knows max_tokens.
        token_field = "max_tokens" if self.provider == "ollama" else "max_completion_tokens"
        kwargs[token_field] = self.max_tokens
        if self.reasoning_effort:
            kwargs["reasoning_effort"] = self.reasoning_effort
        if tools:
            kwargs["tools"] = tools
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = self.client.chat.completions.create(**kwargs)
        message = response.choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=c.function.arguments or "{}")
            for c in (message.tool_calls or [])
        ]
        usage = getattr(response, "usage", None)
        tokens = getattr(usage, "total_tokens", None)
        return AssistantTurn(
            content=message.content or "",
            tool_calls=calls,
            tokens=tokens if isinstance(tokens, int) else None,
        )


def normalise(vectors) -> np.ndarray:
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


class OpenAIEmbedder:
    """Embeddings through the OpenAI API, or through Ollama's OpenAI-compatible API."""

    def __init__(
        self,
        model: str | None = None,
        client=None,
        batch_size: int = 100,
        provider: str | None = None,
    ):
        self.provider, _, default_model = _settings(provider)
        self.model = model or default_model
        self.name = f"{self.provider}:{self.model}"
        self.client = client or make_client(self.provider)
        self.batch_size = batch_size

    def encode(self, texts: list[str]) -> np.ndarray:
        rows: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            # Plain floats: not every OpenAI-compatible server returns the client's default base64.
            response = self.client.embeddings.create(
                model=self.model, input=batch, encoding_format="float"
            )
            rows.extend(item.embedding for item in response.data)
        return normalise(np.array(rows))


def extract_json(text: str):
    """Parse the first JSON object or array in a model reply, tolerating code fences and chatter."""
    text = (text or "").strip()
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON found in model reply")
