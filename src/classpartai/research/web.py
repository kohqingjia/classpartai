"""The web source for search_web, via Tavily (built for LLM agents: it returns cleaned page
extracts, not raw HTML)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str


class WebSearch(Protocol):
    name: str

    def search(self, query: str, k: int = 5) -> list[WebResult]: ...


class TavilySearch:
    def __init__(self, api_key: str | None = None):
        from tavily import TavilyClient

        key = api_key or os.getenv("TAVILY_API_KEY")
        if not key:
            raise RuntimeError("TAVILY_API_KEY is not set")
        self.name = "tavily"
        self.client = TavilyClient(api_key=key)

    def search(self, query: str, k: int = 5) -> list[WebResult]:
        response = self.client.search(query=query, max_results=k, search_depth="basic")
        return [
            WebResult(r.get("title", ""), r.get("url", ""), r.get("content", ""))
            for r in response.get("results", [])
        ]


def default_web_search() -> WebSearch | None:
    """Tavily if a key is configured, else None: the agent then simply has no web tool."""
    try:
        return TavilySearch()
    except RuntimeError:
        return None
