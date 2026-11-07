"""The vector store behind search_course_materials.

Brute-force cosine over every chunk, which the Topic 8 lecture notes is fine at course scale, plus
BM25 keyword search fused with Reciprocal Rank Fusion. Keywords catch exact names and terms
("Gojek", "multi-homing") that embeddings blur. Saved to disk so the course is embedded once,
not on every run.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from rank_bm25 import BM25Okapi

from classpartai.llm import Embedder
from classpartai.research.materials import Chunk, matches

_TOKEN = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


@dataclass
class Hit:
    chunk: Chunk
    score: float  # cosine similarity to the query, -1..1
    rrf: float  # fused rank score, for ordering
    bm25: float | None = None  # diagnostic only; never changes ranking


class VectorStore:
    def __init__(self, chunks: list[Chunk], embeddings: np.ndarray, embedder: Embedder):
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings differ in length")
        self.chunks = chunks
        self.embeddings = np.asarray(embeddings, dtype=np.float32)
        self.embedder = embedder
        self.bm25 = BM25Okapi([tokenize(c.context_text()) or ["_"] for c in chunks])

    @classmethod
    def build(cls, chunks: list[Chunk], embedder: Embedder) -> VectorStore:
        if not chunks:
            raise ValueError("no chunks to index")
        return cls(chunks, embedder.encode([c.context_text() for c in chunks]), embedder)

    def save(self, directory: str | Path) -> None:
        out = Path(directory)
        out.mkdir(parents=True, exist_ok=True)
        np.save(out / "embeddings.npy", self.embeddings)
        lines = [json.dumps(c.to_dict(), ensure_ascii=False) for c in self.chunks]
        (out / "chunks.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        meta = {"embedder": self.embedder.name, "chunks": len(self.chunks)}
        (out / "meta.json").write_text(json.dumps(meta))

    @classmethod
    def load(cls, directory: str | Path, embedder: Embedder) -> VectorStore:
        src = Path(directory)
        if not (src / "meta.json").is_file():
            raise FileNotFoundError(
                f"No index in {src}. Build it with `uv run python -m classpartai.research ingest`."
            )
        meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
        if meta["embedder"] != embedder.name:
            raise ValueError(
                f"The index was built with {meta['embedder']} but the embedder is {embedder.name}. "
                "Rebuild it with `uv run python -m classpartai.research ingest`."
            )
        lines = (src / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        chunks = [Chunk(**json.loads(line)) for line in lines if line.strip()]
        return cls(chunks, np.load(src / "embeddings.npy"), embedder)

    def search(
        self,
        query: str,
        *,
        week: int | None = None,
        week_patterns: list[str] | None = None,
        k: int = 5,
        rrf_k: int = 60,
    ) -> list[Hit]:
        """Top-k chunks for the query. With `week`: that week's material, files matching the
        week's `week_patterns` from the schedule (a deck shared by two weeks), and undated files."""
        patterns = week_patterns or []
        allowed = np.array(
            [
                week is None or c.week in (week, None) or matches(c.doc, patterns)
                for c in self.chunks
            ]
        )
        idx = np.flatnonzero(allowed)
        if len(idx) == 0 or not query.strip():
            return []
        cosine = self.embeddings[idx] @ self.embedder.encode([query])[0]
        bm25 = self.bm25.get_scores(tokenize(query))[idx]
        semantic = list(np.argsort(-cosine))
        keyword = [i for i in np.argsort(-bm25) if bm25[i] > 0]
        fused: dict[int, float] = {}
        for ranked in (semantic, keyword):
            for rank, i in enumerate(ranked, 1):
                fused[int(i)] = fused.get(int(i), 0.0) + 1.0 / (rrf_k + rank)
        best = sorted(fused, key=fused.get, reverse=True)[:k]
        return [Hit(self.chunks[idx[i]], float(cosine[i]), fused[i], float(bm25[i])) for i in best]
