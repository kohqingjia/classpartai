"""The model wrappers send each provider the request fields it accepts."""

from types import SimpleNamespace

import pytest

from classpartai.llm import OpenAIChat, OpenAIEmbedder


class FakeClient:
    """Records the arguments of each call and returns a canned reply."""

    def __init__(self):
        self.chat_kwargs: dict = {}
        self.embed_kwargs: dict = {}
        tool_call = SimpleNamespace(
            id="c1", function=SimpleNamespace(name="get_lesson_context", arguments='{"date": "x"}')
        )
        message = SimpleNamespace(content="", tool_calls=[tool_call])
        self.chat = SimpleNamespace(
            completions=SimpleNamespace(
                create=self._chat(SimpleNamespace(choices=[SimpleNamespace(message=message)]))
            )
        )
        self.embeddings = SimpleNamespace(create=self._embed)

    def _chat(self, reply):
        def create(**kwargs):
            self.chat_kwargs = kwargs
            return reply

        return create

    def _embed(self, **kwargs):
        self.embed_kwargs = kwargs
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[3.0, 4.0]) for _ in kwargs["input"]]
        )


TOOLS = [{"type": "function", "function": {"name": "get_lesson_context", "parameters": {}}}]


def test_openai_uses_max_completion_tokens():
    client = FakeClient()
    chat = OpenAIChat("gpt-5.4-mini", client=client, provider="openai")
    turn = chat.complete([{"role": "user", "content": "hi"}], tools=TOOLS)
    assert chat.name == "openai:gpt-5.4-mini"
    assert "max_completion_tokens" in client.chat_kwargs and "max_tokens" not in client.chat_kwargs
    assert "tool_choice" not in client.chat_kwargs
    assert turn.tool_calls[0].name == "get_lesson_context"


def test_ollama_uses_max_tokens_and_json_mode():
    client = FakeClient()
    chat = OpenAIChat("qwen3:8b", client=client, provider="ollama", reasoning_effort="none")
    chat.complete([{"role": "user", "content": "hi"}], tools=TOOLS, json_mode=True)
    sent = client.chat_kwargs
    assert chat.name == "ollama:qwen3:8b"
    assert sent["max_tokens"] == 4096 and "max_completion_tokens" not in sent
    assert "tool_choice" not in sent and sent["reasoning_effort"] == "none"
    assert sent["response_format"] == {"type": "json_object"}


def test_embedder_asks_for_floats_and_normalises():
    client = FakeClient()
    embedder = OpenAIEmbedder("nomic-embed-text", client=client, provider="ollama")
    vectors = embedder.encode(["a", "b"])
    assert client.embed_kwargs["encoding_format"] == "float"
    assert embedder.name == "ollama:nomic-embed-text"
    assert vectors.shape == (2, 2) and vectors[0] == pytest.approx([0.6, 0.8])


def test_unknown_provider_is_refused():
    with pytest.raises(ValueError, match="LLM_PROVIDER"):
        OpenAIChat(client=FakeClient(), provider="gemini")
