"""Code behind each course topic, for the How it works page.

Snippets are read from the source files when the page renders, so they always show the code that
actually runs. Files are parsed with ``ast``, never imported: the audio service loads its models
at import time.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

from classpartai.config import REPO_ROOT


@dataclass(frozen=True)
class Snippet:
    title: str
    path: str  # relative to the repository root
    names: tuple[str, ...]  # top-level names, or "Class.method"
    say: str  # the point to make when presenting it


TOPICS: list[tuple[str, list[Snippet]]] = [
    (
        "Topic 2 · Transformers: Whisper (Listener)",
        [
            Snippet(
                "Speech to text: Whisper, decoded with beam search",
                "audio-service/transcription.py",
                ("model", "transcribe_audio"),
                "Whisper is an encoder-decoder transformer. 'base' runs int8-quantised on CPU; "
                "beam search keeps the 5 best partial transcripts at each step.",
            ),
        ],
    ),
    (
        "Topics 1 & 8 · Embeddings and cosine similarity: who spoke? (Listener)",
        [
            Snippet(
                "Compare a voice with an enrolled sample",
                "audio-service/speaker_identification.py",
                ("compare_speakers",),
                "SpeechBrain's ECAPA model turns each clip into an embedding; the score is the "
                "cosine similarity of the two embeddings.",
            ),
            Snippet(
                "Name a speaker only when the match is clear",
                "src/classpartai/agents/listener.py",
                ("MATCH_MIN_SCORE", "MATCH_MIN_MARGIN", "best_match"),
                "At least 0.35, and 0.10 ahead of the runner-up; otherwise UNKNOWN or AMBIGUOUS, "
                "and unnamed lines are never scored.",
            ),
        ],
    ),
    (
        "Topic 8 · Agentic RAG: Evidence / Research",
        [
            Snippet(
                "Chunking: overlapping word windows",
                "src/classpartai/research/materials.py",
                ("split_into_chunks",),
                "As in the Topic 8 lab: a window of words, stepping by window − overlap, so a "
                "sentence cut at one boundary is whole in the next chunk.",
            ),
            Snippet(
                "Chunk size and overlap for the course notes",
                "src/classpartai/research/bridge.py",
                ("session_chunks",),
                "120-word windows with a 30-word overlap. The chunk ID keeps its slide or page, "
                "so every citation traces back to its source.",
            ),
            Snippet(
                "Embedding model",
                "src/classpartai/config.py",
                ("OPENAI_EMBEDDING_MODEL",),
                "Chunks and queries are embedded with the same model, so cosine similarity "
                "compares like with like.",
            ),
            Snippet(
                "Hybrid search: BM25 + vectors, fused with RRF",
                "src/classpartai/research/store.py",
                ("VectorStore.search",),
                "Keywords catch exact terms, vectors catch meaning. Reciprocal Rank Fusion adds "
                "1 / (60 + rank) from each list and keeps the top 5.",
            ),
            Snippet(
                "Grade, then retry (corrective RAG)",
                "src/classpartai/research/tools.py",
                ("MAX_ATTEMPTS_PER_SOURCE", "GRADER_PROMPT"),
                "An LLM grades each passage for relevance and stance and must quote it exactly. "
                "Weak evidence triggers a rewritten query: at most 2 rewrites per source.",
            ),
        ],
    ),
    (
        "Topic 7 · Agents: Coordinator, tools and budget",
        [
            Snippet(
                "The tools the Coordinator may call",
                "src/classpartai/participation/coordinator.py",
                ("COORDINATOR_TOOLS",),
                "Each tool has a JSON schema from a Pydantic model; the model picks the next "
                "call. There is no approve or send tool.",
            ),
            Snippet(
                "Its instructions: plan from results, not a fixed script",
                "src/classpartai/participation/coordinator.py",
                ("COORDINATOR_POLICY",),
                '"Choose your next action based on tool results, not a fixed sequence."',
            ),
            Snippet(
                "The budget every run must fit in",
                "src/classpartai/models.py",
                ("WORKFLOW_LIMITS",),
                "72 model calls, 108 tool calls, 400k tokens, 600 s. A run that hits a limit "
                "stops cleanly and leaves its draft for review.",
            ),
        ],
    ),
    (
        "Topic 6 · Evaluation: LLM-as-judge, verify first",
        [
            Snippet(
                "The Judge: rubric scoring, then deterministic validation",
                "src/classpartai/participation/roles.py",
                ("judge",),
                "Scores only attributable participation, or 'insufficient_evidence'. Its output "
                "must pass validate_proposal; a failure goes back to the model with the reason.",
            ),
            Snippet(
                "The Auditor: a second model checks support",
                "src/classpartai/participation/roles.py",
                ("model_audit",),
                "Raises issues for review, never lowers scores itself; deterministic "
                "validation stays authoritative.",
            ),
        ],
    ),
    (
        "Topic 9 · Ethics and security: guardrails",
        [
            Snippet(
                "Every agent's ground rules",
                "src/classpartai/participation/roles.py",
                ("ROLE_POLICY",),
                "Transcript, slides and tool results are untrusted data, never instructions.",
            ),
            Snippet(
                "Flag prompt injection in retrieved text",
                "src/classpartai/research/tools.py",
                ("_INJECTION",),
                "Text that reads like an instruction to the grader is flagged, not followed.",
            ),
            Snippet(
                "Approve the exact version",
                "src/classpartai/participation/records.py",
                ("Records.approval_digest",),
                "A SHA-256 of the content and recipients: any edit after approval no longer "
                "matches, so nothing unapproved can be sent.",
            ),
        ],
    ),
]


def _find(tree: ast.Module, name: str) -> ast.stmt | None:
    owner, _, member = name.rpartition(".")
    body = tree.body
    if owner:
        cls = next((n for n in body if isinstance(n, ast.ClassDef) and n.name == owner), None)
        body = cls.body if cls else []
    for node in body:
        if getattr(node, "name", None) == (member or name):
            return node
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == (member or name) for t in targets):
                return node
    return None


def source(snippet: Snippet, root: Path = REPO_ROOT) -> tuple[str, int] | None:
    """The snippet's code (whole lines, with the comments just above each name) and its first
    line number, or None when the file or a name is missing."""
    path = root / snippet.path
    if not path.exists():
        return None
    text = path.read_text()
    lines, tree = text.splitlines(), ast.parse(text)
    parts, first = [], None
    for name in snippet.names:
        node = _find(tree, name)
        if node is None:
            return None
        start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        while start > 1 and lines[start - 2].lstrip().startswith("#"):
            start -= 1
        block = lines[start - 1 : node.end_lineno]
        indent = min(len(line) - len(line.lstrip()) for line in block if line.strip())
        parts.append("\n".join(line[indent:] for line in block))
        first = first or start
    return "\n\n".join(parts), first
