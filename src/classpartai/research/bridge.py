"""Links ② Research to the assessment workflow on main (assessment.py, evidence.py, coordinator).

Three links:

- ``answer_pairs(transcript)``: the Listener's reviewed transcript as (professor question,
  student answer) pairs, the input Research was built for.
- ``documents_from_materials(...)``: the IS469 lecture files as session documents
  (``assessment.Document``), so any session, and either evidence agent, can search the real
  slides and labs instead of the demo notes. Licensed material: write it under ``var/`` (git-
  ignored), never into ``data/``.
- ``investigate(request, inputs, budget, checkpoint)``: a drop-in for
  ``evidence.investigate``. It runs the Research agent on the session's own documents and hands
  back the same ``AgentOutcome`` and ``EvidenceBundle``, so records, validation, the Judge and the
  UI work unchanged. The agent still chooses course documents or the web per answer; only course
  passages become citations, and web findings are passed on as labelled context. The answer
  assessment (correctness, answers the question, reasoning, kind of mistake, missed points) goes
  in the bundle's explanation for the Judge and, in full, in the saved run's progress.

The coordinator and the app use it by default (``EVIDENCE_AGENT=research``);
``EVIDENCE_AGENT=course`` switches back to the course evidence agent in evidence.py.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date as Date
from pathlib import Path

from classpartai.assessment import AssessmentInputs, Document, Transcript
from classpartai.evidence import (
    AgentOutcome,
    Citation,
    EvidenceBundle,
    EvidenceProgress,
    Investigation,
)
from classpartai.llm import AssistantTurn, ChatModel, Embedder
from classpartai.models import WORKFLOW_LIMITS, BudgetExceeded, SharedBudget
from classpartai.research.agent import EvidencePack, ResearchAgent
from classpartai.research.materials import (
    _COPY_SUFFIX,
    KIND_BY_SUFFIX,
    SUPPORTED,
    Chunk,
    _week_of,
    matches,
    read_pages,
    split_into_chunks,
)
from classpartai.research.store import VectorStore

MAX_RUNS = 2  # answers researched per investigation (one per student); each run costs ~10 calls
STANCE_TO_RELATIONSHIP = {"supports": "supports", "contradicts": "conflicts", "neither": "context"}

# --- ① Listener -> ② Research ------------------------------------------------------------------


@dataclass
class AnswerPair:
    question_turn: str | None  # the professor's turn, or None for an unprompted contribution
    question: str | None
    student_id: str
    turn_ids: list[str]
    answer: str
    start_ms: int

    def contribution(self) -> dict:
        """The shape ResearchAgent.research_contribution takes."""
        seconds = self.start_ms // 1000
        return {
            "id": self.turn_ids[0],
            "student": self.student_id,
            "question": self.question,
            "text": self.answer,
            "timestamp": f"{seconds // 60:02d}:{seconds % 60:02d}",
        }


def answer_pairs(transcript: Transcript, turn_ids: list[str] | None = None) -> list[AnswerPair]:
    """Each student's answer with the professor question it follows. Consecutive turns by the
    same student are one answer; uncertain speakers are skipped (they can't establish a score).
    With ``turn_ids``, only answers that include one of those turns."""
    pairs: list[AnswerPair] = []
    question: tuple[str, str] | None = None
    for turn in transcript.turns:
        speaker = turn.speaker
        if speaker.kind == "professor":
            question = (turn.id, turn.text)
            continue
        if speaker.kind != "student":
            continue
        last = pairs[-1] if pairs else None
        if (
            last
            and last.student_id == speaker.studentId
            and last.question_turn == (question[0] if question else None)
            and last.turn_ids[-1] == _previous_id(transcript, turn.id)
        ):
            last.turn_ids.append(turn.id)
            last.answer += " " + turn.text
            continue
        pairs.append(
            AnswerPair(
                question[0] if question else None,
                question[1] if question else None,
                speaker.studentId,
                [turn.id],
                turn.text,
                turn.startMs,
            )
        )
    if turn_ids is not None:
        wanted = set(turn_ids)
        pairs = [p for p in pairs if wanted & set(p.turn_ids)]
    return pairs


def _previous_id(transcript: Transcript, turn_id: str) -> str | None:
    ids = [t.id for t in transcript.turns]
    i = ids.index(turn_id)
    return ids[i - 1] if i else None


# --- Lecture files -> session documents --------------------------------------------------------


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", text).strip("-")[:80] or "doc"


def documents_from_materials(materials_dir: str | Path, max_chars: int = 20000) -> list[dict]:
    """One ``assessment.Document`` per lecture file, one passage per slide, page or cell group.
    The file name goes in ``source`` so Research can still tell which week a file belongs to."""
    root = Path(materials_dir)
    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
        and not p.name.startswith(".")
        and p.stem.lower() != "readme"
    )
    documents, used = [], set()
    for path in files:
        relative = path.relative_to(root).as_posix()
        doc_id = _slug(_COPY_SUFFIX.sub("", path.stem))
        while doc_id in used:
            doc_id = _slug(doc_id[:76] + "-" + hashlib.md5(relative.encode()).hexdigest()[:3])
        used.add(doc_id)
        passages, keys = [], set()
        for page, text in read_pages(path):
            text = text.strip()
            for n, start in enumerate(range(0, len(text), max_chars)):
                piece = text[start : start + max_chars].strip()
                if not piece:
                    continue
                key = f"p{page or 1}" + (f"-{n + 1}" if n else "")
                while key in keys:
                    key += "b"
                keys.add(key)
                passages.append({"id": key, "page": max(1, page or 1), "text": piece})
        if not passages:
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        documents.append(
            {
                "id": doc_id,
                "version": digest,
                "title": re.sub(r"[_-]+", " ", _COPY_SUFFIX.sub("", path.stem)).strip()[:200],
                "source": f"IS469 course materials: {relative}"[:200],
                "authorisedForCourse": True,
                "passages": passages[:1000],
            }
        )
    if not documents:
        raise ValueError(f"No slides, readings or labs found under {root}")
    return documents[:100]


# --- Session documents -> Research's index -----------------------------------------------------

_FILE_IN_SOURCE = re.compile(r"[^\s:/][^:]*?\.(?:pptx|pdf|ipynb|md|txt)\b", re.IGNORECASE)


def passage_id(doc: Document, key: str) -> str:
    """The passage ID the course evidence agent uses, so citations from either agent match."""
    return f"{doc.id}:{doc.version}:{key}"


def session_chunks(
    documents: list[Document], schedule: dict | None, window: int = 120, overlap: int = 30
) -> list[Chunk]:
    """The session's authorised passages as Research chunks. A chunk's id is
    ``<passageId>#<n>`` so every citation traces back to its passage."""
    chunks = []
    for doc in documents:
        found = _FILE_IN_SOURCE.search(doc.source)
        name = found.group(0).strip() if found else f"{doc.title} {doc.id}"
        kind = KIND_BY_SUFFIX.get(Path(name).suffix.lower(), "reading")
        week = _week_of(name, schedule) or _week_of(f"{doc.title} {doc.id}", schedule)
        if schedule is not None and not any(
            matches(name, w.get("materials", [])) for w in schedule.get("weeks", [])
        ):
            # Not one of the course's own files (e.g. a session's "Week 10 notes"): its week
            # number may mean another course's week, so it stays searchable in every week.
            week = None
        for p in doc.passages:
            pid = passage_id(doc, p.id)
            for n, piece in enumerate(split_into_chunks(p.text, window, overlap)):
                chunks.append(Chunk(f"{pid}#{n}", piece, kind, name, doc.title, week, p.page))
    return chunks


def session_store(
    inputs: AssessmentInputs,
    embedder: Embedder,
    schedule: dict | None,
    cache_dir: str | Path | None = None,
) -> VectorStore:
    """An index of exactly this session's documents (scope can't leak across sessions), cached
    by content so a session's documents are embedded once."""
    chunks = session_chunks(inputs.documents, schedule)
    if cache_dir is None:
        return VectorStore.build(chunks, embedder)
    fingerprint = hashlib.sha256(
        json.dumps([embedder.name, [[c.id, c.text, c.week] for c in chunks]]).encode()
    ).hexdigest()[:16]
    directory = Path(cache_dir) / fingerprint
    if (directory / "meta.json").is_file():
        try:
            return VectorStore.load(directory, embedder)
        except ValueError:
            pass  # saved with another embedder: rebuild
    store = VectorStore.build(chunks, embedder)
    store.save(directory)
    return store


# --- The shared budget -------------------------------------------------------------------------


class BudgetedChat:
    """Charges every Research model call (agent turns and grader calls) to the coordinator's
    shared budget, the way SharedBudget.wrap does for a Driver."""

    def __init__(self, inner: ChatModel, budget: SharedBudget, progress: EvidenceProgress):
        self.inner, self.budget, self.progress = inner, budget, progress
        self.name = inner.name

    def complete(self, messages, tools=None, json_mode=False) -> AssistantTurn:
        shared = self.budget.progress if self.budget else None
        estimate = len(json.dumps([messages, tools]).encode()) // 4 + 4000
        if self.budget and (
            self.budget.expired()
            or shared.modelCalls >= WORKFLOW_LIMITS["modelCalls"]
            or shared.tokens + estimate > WORKFLOW_LIMITS["tokens"]
        ):
            raise BudgetExceeded()
        self.progress.modelCalls += 1
        if shared:
            shared.modelCalls += 1
            self.budget.checkpoint()
        turn = self.inner.complete(messages, tools=tools, json_mode=json_mode)
        tokens = turn.tokens if turn.tokens is not None else estimate
        self.progress.tokens += tokens
        if shared:
            shared.tokens += tokens
            if turn.tokens is None:
                shared.usageKind = "includes_estimates"
            self.budget.checkpoint()
            if shared.tokens > WORKFLOW_LIMITS["tokens"]:
                raise BudgetExceeded()
        return turn


# --- EvidencePack -> EvidenceBundle ------------------------------------------------------------


def exact_excerpt(quote: str, text: str) -> str | None:
    """The quote as it appears in the passage. Research's chunks normalise whitespace, and the
    validator wants the passage's own characters."""
    if not quote.strip():
        return None
    if quote in text:
        return quote
    words = quote.split()
    found = re.search(r"\s+".join(re.escape(w) for w in words), text)
    return found.group(0) if found else None


def _passages(inputs: AssessmentInputs) -> dict[str, tuple[Document, object]]:
    return {passage_id(d, p.id): (d, p) for d in inputs.documents for p in d.passages}


def citations_for(
    packs: list[EvidencePack], inputs: AssessmentInputs
) -> list[tuple[Citation, str]]:
    """Every graded course quote behind a claim, as (citation of its passage, the claim)."""
    passages = _passages(inputs)
    out, seen = [], set()
    for pack in packs:
        for claim in pack.claims:
            for ev in claim["evidence"]:
                pid = (ev.get("chunk_id") or "").rsplit("#", 1)[0]
                if pid not in passages or ev.get("relevance") == "irrelevant":
                    continue
                doc, passage = passages[pid]
                excerpt = exact_excerpt(ev.get("quote", ""), passage.text)
                relationship = STANCE_TO_RELATIONSHIP.get(ev.get("stance"), "context")
                key = (pid, excerpt, relationship)
                if excerpt is None or key in seen:
                    continue
                seen.add(key)
                why = f"{ev.get('relevance')} to the claim: {claim['claim']}"
                if ev.get("reason"):
                    why += f" ({ev['reason']})"
                out.append(
                    (
                        Citation(
                            passageId=pid,
                            documentId=doc.id,
                            version=doc.version,
                            title=doc.title,
                            source=doc.source,
                            passageKey=passage.id,
                            page=passage.page,
                            excerpt=excerpt[:2000],
                            relevance=why[:800],
                            relationship=relationship,
                        ),
                        claim["claim"],
                    )
                )
    return out[:12]


def explanation_for(packs: list[EvidencePack], students: list[str]) -> str:
    """The answer assessment, compactly, for the Judge (it reads the bundle as JSON)."""
    parts = []
    for student, pack in zip(students, packs, strict=True):
        head = f"Research on {student}'s answer"
        if pack.question:
            head += f' to the professor\'s question "{pack.question}"'
        if pack.focus:
            head += f', for the investigation question "{pack.focus}"'
        fields = [
            f"correctness: {pack.correctness or 'no claim'}",
            f"answers the question: {pack.answers_question or 'n/a'}",
            f"reasoning: {pack.reasoning or 'n/a'}",
        ]
        if pack.mistake:
            fields.append(f"mistake: {pack.mistake['type']} ({pack.mistake.get('reason', '')})")
        if pack.on_topic is False:
            fields.append(f"off topic ({pack.on_topic_reason})")
        lines = [f"{head}: " + "; ".join(fields) + f". Sources searched: {pack.route}."]
        for c in pack.claims:
            lines.append(f"- claim ({c['status']}): {c['claim']}")
            # Web evidence can't be a citation (citations are session passages only), so the
            # Judge sees it here, labelled, with its link.
            lines += [
                f'  web context ({e["relevance"]}, {e["stance"]}): "{e["quote"]}" ({e["url"]})'
                for e in c["evidence"]
                if e.get("source_type") == "web" and e.get("quote")
            ]
        if pack.missed_points:
            lines.append("Missed points: " + "; ".join(pack.missed_points))
        if pack.summary:
            lines.append(f"Summary: {pack.summary}")
        lines += [f"Note: {n}" for n in pack.notes]
        parts.append("\n".join(lines))
    parts.append(
        "Signals for the Judge, not scores; a reasonable guess is not a misconception. Web "
        "context is not course evidence and cannot be cited. Support interpretations remain for "
        "professor review."
    )
    return "\n\n".join(parts)


def bundle_for(
    packs: list[EvidencePack],
    students: list[str],
    request: Investigation,
    inputs: AssessmentInputs,
    stopped: str | None = None,
    skipped: list[AnswerPair] = (),
) -> EvidenceBundle:
    cited = citations_for(packs, inputs)
    citations = [c for c, _ in cited]
    contradicted = {claim for c, claim in cited if c.relationship == "conflicts"}
    backed = {claim for c, claim in cited if c.relationship in ("supports", "conflicts")}
    conflicts = [
        f"The course contradicts: {c['claim']}"
        for p in packs
        for c in p.claims
        if c["status"] in ("contradicted", "mixed") and c["claim"] in contradicted
    ][:8]
    # Turns asked about but not researched come first, so the cap can't hide them.
    gaps = [
        f"Not researched (at most {MAX_RUNS} answers per investigation): "
        f"{', '.join(p.turn_ids)} ({p.student_id})"
        for p in skipped
    ]
    # Every claim without a quoted course passage for or against it stays an open question,
    # whatever verdict the pack gives it (partial, web-only or unverified evidence).
    for pack in packs:
        for c in pack.claims:
            if c["claim"] in backed:
                continue
            if c["status"] == "unverified":
                gaps.append(f"No course passage found for: {c['claim']}")
            elif any(e.get("source_type") == "web" for e in c["evidence"]):
                gaps.append(f"Only web context, no course passage, for: {c['claim']}")
            else:
                gaps.append(f"No quoted course passage settles ({c['status']}): {c['claim']}")
    if stopped:
        gaps.append(f"Unresolved investigation: {stopped}")
    if not citations and not gaps:
        gaps.append("No course passage supported or contradicted the answer")
    return EvidenceBundle(
        sessionId=request.sessionId,
        question=request.question,
        transcriptVersion=inputs.transcript.version,
        rubric={
            "id": inputs.rubric.id,
            "version": inputs.rubric.version,
            "criterionIds": request.criterionIds,
        },
        status="sufficient" if citations and not gaps else "gap",
        explanation=explanation_for(packs, students) if packs else "Research did not run",
        turnIds=request.turnIds,
        citations=citations,
        conflicts=conflicts,
        gaps=gaps[:8],
    )


def choose_pairs(pairs: list[AnswerPair]) -> tuple[list[AnswerPair], list[AnswerPair]]:
    """(at most MAX_RUNS answers to research, the rest). Each student's first answer comes
    before anyone's second, so one student can't use up both runs."""
    seen: set[str] = set()
    firsts = [p for p in pairs if not (p.student_id in seen or seen.add(p.student_id))]
    ranked = firsts + [p for p in pairs if all(p is not f for f in firsts)]
    chosen = {id(p) for p in ranked[:MAX_RUNS]}
    return [p for p in pairs if id(p) in chosen], [p for p in pairs if id(p) not in chosen]


# --- The drop-in for evidence.investigate ------------------------------------------------------


@dataclass
class ResearchProgress(EvidenceProgress):
    """EvidenceProgress plus the full evidence packs (saved with the run by Records)."""

    research: list[dict] | None = None
    lastTool: str | None = None  # the tool running now, for the UI's live view


def _actions(pack: EvidencePack, offset: int) -> list[dict]:
    return [
        {
            "id": f"{offset + i + 1}:research",
            "tool": step["tool"],
            "arguments": json.dumps(step["args"])[:1000],
            "outcome": "ok" if step["ok"] else "invalid",
            "resultReferences": [],
            "summary": step["result"][:300],
        }
        for i, step in enumerate(pack.trajectory)
    ]


AgentFactory = Callable[[ChatModel], ResearchAgent]


def default_agent_factory(light: bool = True) -> AgentFactory:
    """Research on the configured models, the course schedule and, when RESEARCH_BRIDGE_WEB is on
    and TAVILY_API_KEY is set, the web: the agent decides per answer whether the session's course
    documents or the web fit. Citations stay course-only (the workflow's validator only accepts
    session passages); web findings reach the Judge as labelled context. ``light`` uses the
    smaller in-workflow budgets (RESEARCH_BRIDGE_*); False uses Research's own (RESEARCH_*)."""
    from classpartai import config
    from classpartai.llm import OpenAIChat, OpenAIEmbedder
    from classpartai.research.materials import load_schedule
    from classpartai.research.web import default_web_search

    schedule = load_schedule(config.COURSE_DIR)
    web = default_web_search() if config.RESEARCH_BRIDGE_WEB else None
    embedder = OpenAIEmbedder()
    chat = OpenAIChat()
    stores: dict[int, VectorStore] = {}

    def make(inputs: AssessmentInputs):
        key = id(inputs)
        if key not in stores:
            stores.clear()
            stores[key] = session_store(
                inputs, embedder, schedule, config.DATA_DIR / "research-index"
            )

        def factory(wrap: Callable[[ChatModel], ChatModel]) -> ResearchAgent:
            return ResearchAgent(
                wrap(chat),
                stores[key],
                schedule,
                web,
                max_steps=config.RESEARCH_BRIDGE_MAX_STEPS if light else config.RESEARCH_MAX_STEPS,
                max_course_searches=(
                    config.RESEARCH_BRIDGE_MAX_COURSE_SEARCHES
                    if light
                    else config.RESEARCH_MAX_COURSE_SEARCHES
                ),
                max_web_searches=(
                    config.RESEARCH_BRIDGE_MAX_WEB_SEARCHES
                    if light
                    else config.RESEARCH_MAX_WEB_SEARCHES
                ),
                max_grades=(
                    config.RESEARCH_BRIDGE_MAX_GRADES if light else config.RESEARCH_MAX_GRADES
                ),
            )

        return factory

    return make


_default = None


def investigate(
    request: Investigation,
    inputs: AssessmentInputs,
    budget: SharedBudget | None = None,
    checkpoint: Callable[[EvidenceProgress], None] = lambda progress: None,
    *,
    agent: Callable[[Callable[[ChatModel], ChatModel]], ResearchAgent] | None = None,
    date: str | None = None,
) -> AgentOutcome:
    """Research the student answers in ``request.turnIds`` (or, with none, the request's own
    question) and return what evidence.investigate returns.

    ``agent(wrap)`` builds a ResearchAgent whose model is ``wrap(model)``; the default uses the
    configured models and an index of this session's documents."""
    global _default
    if agent is None:
        _default = _default or default_agent_factory()
        agent = _default(inputs)
    progress = ResearchProgress(research=[])
    day = date or Date.today().isoformat()
    turns = {t.id for t in inputs.transcript.turns}
    criteria = {c.id for c in inputs.rubric.criteria}
    if any(t not in turns for t in request.turnIds) or any(
        c not in criteria for c in request.criterionIds
    ):
        raise ValueError("Unknown transcript turn or rubric criterion")
    pairs, skipped = choose_pairs(answer_pairs(inputs.transcript, request.turnIds))
    packs, students, stopped = [], [], None

    def charge(tool: str) -> None:
        # Counted before the tool runs: the coordinator's checkpoint charges the shared budget
        # and raises BudgetExceeded when it is spent, which stops Research there.
        progress.toolCalls += 1
        progress.lastTool = tool
        checkpoint(progress)

    try:
        for pair in pairs or [None]:
            research = agent(lambda model: BudgetedChat(model, budget, progress))
            research.on_tool = charge
            if pair is None:  # no student answer among the turns: research the question itself
                pack = research.answer_question(request.question, day)
                student = "the investigation"
            else:
                # The investigator's question goes with the answer: it is what was asked for,
                # and the professor's question stays as the answer's context.
                contribution = {**pair.contribution(), "focus": request.question}
                pack = research.research_contribution(contribution, day)
                student = pair.student_id
            packs.append(pack)
            students.append(student)
            progress.actions += _actions(pack, len(progress.actions))
            progress.research.append(pack.to_dict())
            checkpoint(progress)
    except BudgetExceeded:
        stopped = "shared_budget"
    except Exception as error:  # provider failure: keep a gap bundle, never fabricate
        status = re.search(r"HTTP (\d{3})", str(error)) or re.search(
            r"Error code: (\d{3})", str(error)
        )
        stopped = f"provider_http_{status[1]}" if status else "provider_failure"
    progress.bundle = bundle_for(packs, students, request, inputs, stopped, skipped)
    progress.returnedCharacters = sum(len(c.excerpt) for c in progress.bundle.citations)
    if stopped == "shared_budget":
        return AgentOutcome("needs_review", "shared_budget", progress)
    if stopped:
        return AgentOutcome("failed", stopped, progress)
    if (
        progress.bundle.status == "sufficient"
        and not skipped
        and not any(p.needs_review for p in packs)
    ):
        return AgentOutcome("completed", "research_sufficient", progress)
    return AgentOutcome("needs_review", "research_gap_or_review", progress)
