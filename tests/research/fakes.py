"""Offline stand-ins for the embedder, the model and web search."""

from __future__ import annotations

import hashlib
import itertools
import json
import re

import numpy as np

from classpartai.llm import AssistantTurn, ToolCall, normalise
from classpartai.research.store import tokenize
from classpartai.research.web import WebResult


class HashEmbedder:
    """Bag of words hashed into a fixed-size vector: crude and deterministic, enough to rank."""

    name = "test:hash"

    def encode(self, texts):
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text):
                out[row, int(hashlib.md5(token.encode()).hexdigest(), 16) % 256] += 1.0
        return normalise(out)


_ids = itertools.count(1)


def call(name: str, **args) -> ToolCall:
    return ToolCall(id=f"call_{next(_ids)}", name=name, arguments=json.dumps(args))


def turn(*calls: ToolCall, content: str = "") -> AssistantTurn:
    return AssistantTurn(content=content, tool_calls=list(calls))


def submit(claims=(), summary="See the evidence.", on_topic=True, route_reason="test") -> ToolCall:
    return call(
        "submit_findings",
        route_reason=route_reason,
        on_topic=on_topic,
        on_topic_reason="test",
        claims=list(claims),
        summary=summary,
    )


_POINT = re.compile(r'<expected_point id="([^"]+)">(.*?)</expected_point>', re.DOTALL)
_ANSWER = re.compile(r"<student_answer>(.*?)</student_answer>", re.DOTALL)


def overlap_coverage(answer: str, points: list[str]) -> list[str]:
    """Default coverage rule: a point is covered if half its content words are in the answer."""
    from classpartai.research.agent import _content_words

    said = _content_words(answer)
    out = []
    for point in points:
        words = _content_words(point)
        share = len(words & said) / len(words) if words else 0
        out.append("covered" if share >= 0.5 else "partly" if share >= 0.25 else "missed")
    return out


_PASSAGE = re.compile(r'<passage id="([^"]+)"[^>]*>\n(.*?)\n</passage>', re.DOTALL)
_CLAIM = re.compile(r"<claim>(.*?)</claim>", re.DOTALL)


def keyword_grader(rules: dict[str, tuple[str, str]] | None = None):
    """A grading rule: a passage containing a keyword gets that (relevance, stance) and, as its
    quote, the sentence with the keyword. Everything else is irrelevant."""
    rules = rules or {}

    def grade(claim: str, passages: list[tuple[str, str]]) -> list[dict]:
        rows = []
        for pid, text in passages:
            row = {"id": pid, "relevance": "irrelevant", "stance": "neither", "quote": ""}
            for keyword, (relevance, stance) in rules.items():
                if keyword.lower() in text.lower():
                    quote = next(
                        s for s in re.split(r"(?<=\.)\s+", text) if keyword.lower() in s.lower()
                    )
                    row = {"id": pid, "relevance": relevance, "stance": stance, "quote": quote}
                    break
            rows.append(row)
        return rows

    return grade


class ScriptedLLM:
    """Plays the agent from a script, and the grader from a rule.

    Each script entry is an AssistantTurn, or a function(messages) -> AssistantTurn so a step can
    read earlier tool results (for example to grade the ids a search returned)."""

    name = "test:scripted"

    def __init__(self, script=(), grader=None, coverage=None, quality=None):
        self.script = list(script)
        self.grader = grader or keyword_grader()
        self.coverage = coverage or overlap_coverage
        # quality(answer) -> (reasoning, mistake dict or None) for the answer assessment
        self.quality = quality or (
            lambda answer: ("explained" if "because" in answer.lower() else "asserted", None)
        )
        self.coverage_prompts: list[str] = []
        self.agent_calls: list[dict] = []
        self.grader_prompts: list[str] = []

    def complete(self, messages, tools=None, json_mode=False):
        if json_mode and "<student_answer>" in messages[-1]["content"]:  # the answer assessment
            prompt = messages[-1]["content"]
            self.coverage_prompts.append(prompt)
            found = _POINT.findall(prompt)
            answer = _ANSWER.search(prompt).group(1)
            statuses = self.coverage(answer, [p for _, p in found]) if found else []
            rows = [{"id": pid, "coverage": c} for (pid, _), c in zip(found, statuses, strict=True)]
            reasoning, mistake = self.quality(answer)
            reply = {"points": rows, "reasoning": reasoning, "mistake": mistake}
            return AssistantTurn(content=json.dumps(reply))
        if json_mode:  # the grade_evidence call
            prompt = messages[-1]["content"]
            self.grader_prompts.append(prompt)
            claim = _CLAIM.search(prompt).group(1)
            rows = self.grader(claim, _PASSAGE.findall(prompt))
            return AssistantTurn(content=json.dumps({"grades": rows}))
        self.agent_calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        if not self.script:
            raise AssertionError("ScriptedLLM ran out of turns")
        step = self.script.pop(0)
        return step(messages) if callable(step) else step

    def tool_names(self, i: int = 0) -> list[str]:
        return [t["function"]["name"] for t in self.agent_calls[i]["tools"]]


class FakeWeb:
    name = "fake-web"

    def __init__(self, results=None):
        self.queries: list[str] = []
        self.results = results or [
            WebResult(
                "Ethernet history",
                "https://example.com/metcalfe",
                "Metcalfe's law is named after Bob Metcalfe, co-inventor of Ethernet.",
            )
        ]

    def search(self, query, k=5):
        self.queries.append(query)
        return self.results[:k]


def last_tool_result(messages) -> str:
    return next(m["content"] for m in reversed(messages) if m["role"] == "tool")


def ids_in(text: str, prefix: str = "C") -> list[str]:
    return list(dict.fromkeys(re.findall(rf"\[({prefix}\d+)\]", text)))
