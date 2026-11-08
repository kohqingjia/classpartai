"""Code behind each course topic, for the How it works page.

Snippets are read from the source files when the page renders, so they always show the code that
actually runs. Files are parsed with ``ast``, never imported: the audio service loads its models
at import time.

A name is a top-level name, ``Class.method``, ``function.inner`` (a function defined inside
another, like the Judge's tools), or ``function#tool``: the branch of
``function`` that handles that tool (``if call.name == "tool":``), for agents whose tools are
handled inside their loop. ``AGENTS`` lists every agent and its tools, for the How it works
catalogue.
"""

import ast
from dataclasses import dataclass
from pathlib import Path

from classpartai.config import REPO_ROOT


@dataclass(frozen=True)
class Snippet:
    title: str
    path: str  # relative to the repository root
    names: tuple[str, ...]  # top-level names, "Class.method" or "function.inner"
    say: str  # the point to make when presenting it


@dataclass(frozen=True)
class Tool:
    name: str  # exactly as the model sees it
    does: str
    takes: str
    returns: str
    guard: str  # its guardrail, or ""
    path: str
    names: tuple[str, ...]  # where it's implemented (see the module docstring)

    @property
    def snippet(self) -> Snippet:
        return Snippet(self.name, self.path, self.names, self.does)


@dataclass(frozen=True)
class Agent:
    name: str
    kind: str  # "agent" (its own loop), "model call", "pipeline" or "code"
    owner: str
    summary: str
    called_by: str  # how it's started
    tools: tuple[Tool, ...] = ()
    code: tuple[Snippet, ...] = ()  # for parts without tools: their prompt or code


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
            Snippet(
                "Split Whisper's pieces where the speaker changes",
                "src/classpartai/agents/listener.py",
                ("align_words",),
                "Each word goes to the diarised turn it falls in, so a piece that runs across a "
                "turn change no longer gives the next speaker's first words to the last one.",
            ),
            Snippet(
                "Check a line, and its whole turn, on their own voice",
                "src/classpartai/agents/listener.py",
                ("MIN_SEGMENT_SECONDS", "veto", "turn_runs"),
                "A line that clearly sounds like someone else becomes AMBIGUOUS. Lines under 1 s "
                "can't be checked alone, so consecutive lines of one speaker are also checked "
                "as one turn.",
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
                "72 model calls, 108 tool calls, 400k tokens, 900 s. A run that hits a limit "
                "stops cleanly and leaves its draft for review.",
            ),
        ],
    ),
    (
        "Topic 6 · Evaluation: LLM-as-judge, verify first",
        [
            Snippet(
                "The Judge: an agent with tools, then deterministic validation",
                "src/classpartai/participation/judge.py",
                ("JUDGE_TOOLS",),
                "The Judge picks its next tool: rubric, evidence, a student's own turns, score, "
                "flag, finish. Every score must pass validate_proposal; a refusal goes back to "
                "the model with the reason.",
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


COORD = "src/classpartai/participation/coordinator.py"
RESEARCH = "src/classpartai/research/tools.py"
AUDIT = "src/classpartai/participation/auditor.py"
JUDGE = "src/classpartai/participation/judge.py"

AGENTS: list[Agent] = [
    Agent(
        "Coordinator",
        "agent",
        "Le Yong (design, TypeScript); ported to Python and integrated by QJ",
        "Plans the whole assessment. Each turn it reads what its last tool returned and picks "
        "the next tool. There is no fixed order and no approve or send tool. Every model and "
        "tool call, its sub-agents' included, counts against one budget (72 model calls, 108 "
        "tool calls, 400k tokens, 900 s).",
        "the ③ Run button",
        (
            Tool(
                "inspect_transcript_context",
                "Reads the reviewed transcript around chosen turns, or every turn of one "
                "student, so the Coordinator can see context before deciding to search.",
                "studentId (optional), up to 12 turnIds",
                "those turns plus each one's neighbours, at most 20",
                "Unknown students or turn IDs are refused.",
                COORD,
                ("_coordinate#inspect_transcript_context",),
            ),
            Tool(
                "retrieve_evidence",
                "Starts the Research agent on one question about what students said, or reuses "
                "an earlier run's evidence. The evidence is saved as its own run.",
                "a question, 1-8 turnIds, 1-6 criterionIds, or reuseRunId",
                "the evidence run's ID, status and its evidence bundle",
                "Research's tool calls count against the Coordinator's budget.",
                COORD,
                ("_coordinate#retrieve_evidence",),
            ),
            Tool(
                "propose_rubric_assessment",
                "Starts the Judge agent: a score per student per criterion, or 'insufficient "
                "evidence'. A revision re-scores only the students the audit raised. The "
                "result is saved as a new draft version.",
                "a note saying why (e.g. 'revise after audit')",
                "the new draft's ID, its findings and audit issues",
                "Every score is validated: right students, existing turns, the student's own "
                "turns, the rubric's range. A failure goes back to the Judge with the reason.",
                COORD,
                ("_coordinate#propose_rubric_assessment",),
            ),
            Tool(
                "audit_assessment",
                "Runs the Auditor agent on the latest draft (a single model call if the agent "
                "fails) and saves its issues with a new version.",
                "a note",
                "the new draft's ID and its audit",
                "Refused before any draft exists. The Auditor never changes a score.",
                COORD,
                ("_coordinate#audit_assessment",),
            ),
            Tool(
                "draft_student_feedback",
                "Asks the Feedback writer for one student's feedback: what went well and one "
                "next step, citing their turns. It may instead ask for more evidence.",
                "a studentId",
                "the new draft's ID, or a request for more evidence",
                "Refused before findings exist ('Create findings before feedback'), or when "
                "the writer returns a different student.",
                COORD,
                ("_coordinate#draft_student_feedback",),
            ),
            Tool(
                "request_professor_review",
                "Ends the run and hands the draft to the professor in ④ Approve.",
                "a summary for the professor",
                "the run's end",
                "Refused until every student has findings and feedback and the latest version "
                "is audited. The third refusal ends the run as 'escalated with open issues'. It "
                "never approves or sends.",
                COORD,
                ("_coordinate#request_professor_review",),
            ),
        ),
    ),
    Agent(
        "Research",
        "agent",
        "Tasmin",
        "Agentic RAG. Checks what a student said against the course notes: it writes its own "
        "queries, searches, grades what it finds, searches again if the evidence is weak (at "
        "most twice), and cites only exact quotes from the notes.",
        "the Coordinator's retrieve_evidence",
        (
            Tool(
                "get_lesson_context",
                "Looks up the seminar on a date in the course schedule, so the agent knows "
                "what's on-topic and which week to search.",
                "a date",
                "week number, topic, key concepts and discussion prompts",
                "",
                RESEARCH,
                ("ResearchTools._lesson",),
            ),
            Tool(
                "search_course_materials",
                "Hybrid search of the session's course library: BM25 keywords and embedding "
                "vectors, fused with Reciprocal Rank Fusion.",
                "a query, optional week, k (1-8, default 5)",
                "chunks with their source: deck and slide, or file and page",
                "Retrieved text is data, never instructions: text that reads like an "
                "instruction is flagged.",
                RESEARCH,
                ("ResearchTools._search_course",),
            ),
            Tool(
                "search_web",
                "Searches the public web, for facts the course notes couldn't contain.",
                "a query, k",
                "snippets with URLs",
                "Off on the live site (no Tavily key), so the agent isn't offered it. Web "
                "results are context only, never cited as evidence.",
                RESEARCH,
                ("ResearchTools._search_web",),
            ),
            Tool(
                "grade_evidence",
                "An LLM grades retrieved chunks against one claim (corrective RAG).",
                "a claim, up to 8 chunk IDs from its searches",
                "per chunk: relevant / partial / irrelevant, supports or contradicts, an "
                "exact quote; overall: sufficient, weak or none",
                "A quote not found word for word in the chunk is dropped, and without one the "
                "verdict can't be decisive.",
                RESEARCH,
                ("ResearchTools._grade",),
            ),
            Tool(
                "submit_findings",
                "Finishes: hands every graded claim and expected point back to the Coordinator.",
                "the claims, as worded when graded",
                "the evidence pack for the Coordinator",
                "Unfinished work (e.g. a claim not yet graded) is sent back once with what's "
                "missing, while there's budget; the second submission is accepted.",
                "src/classpartai/research/agent.py",
                ("ResearchAgent.run#submit_findings",),
            ),
        ),
    ),
    Agent(
        "Auditor",
        "agent",
        "Le Yong (design); merged into the app's own types and loop by Saurabh",
        "Checks the Judge's work before the professor sees it: are scores supported, are "
        "citations real, is anything an injection, is it fair? It raises issues and may ask "
        "for one targeted re-judge, but never changes a score itself.",
        "the Coordinator's audit_assessment",
        (
            Tool(
                "get_session_scores",
                "Reads the Judge's findings and rationales, ten at a time.",
                "offset, limit (1-10)",
                "a page of findings",
                "",
                AUDIT,
                ("AuditTools.get_session_scores",),
            ),
            Tool(
                "compare_similar",
                "Finds the contributions most similar to one finding's, to check that similar "
                "answers got similar scores.",
                "a findingId, k (1-5)",
                "the most similar findings with their scores",
                "",
                AUDIT,
                ("AuditTools.compare_similar",),
            ),
            Tool(
                "verify_citation",
                "Fetches one piece of evidence a finding cites, checks the reference and "
                "quote are real, and has a model judge whether it supports the rationale.",
                "a findingId, an evidenceId attached to it",
                "supports / partly supports / contradicts / fails to verify, with the quote",
                "Only evidence attached to that finding can be fetched.",
                AUDIT,
                ("AuditTools.verify_citation",),
            ),
            Tool(
                "score_stats",
                "A fairness check: do scores track speaking time or transcription confidence?",
                "nothing",
                "correlations with their sample size and missing data",
                "Reports correlation, never claims it proves bias.",
                AUDIT,
                ("AuditTools.score_stats",),
            ),
            Tool(
                "request_rejudge",
                "Objects to specific findings and asks the Judge for one targeted revision.",
                "1-20 issues",
                "the objections, handed back to the Coordinator",
                "One re-judge round per audit. It may not propose a replacement grade.",
                AUDIT,
                ("AuditTools.request_rejudge",),
            ),
            Tool(
                "complete_audit",
                "Finishes the audit with a verdict and its issues.",
                "verdict (audit passed / professor review required), issues, resolvedIssueIds",
                "the audit, saved with the draft",
                "A pass is blocked while required checks are missing; it says which.",
                AUDIT,
                ("complete",),
            ),
        ),
    ),
    Agent(
        "Judge",
        "agent",
        "Saurabh",
        "An agent: gets the rubric, each student's own turns and the evidence summary at once, "
        "scores every student on each criterion (or says 'insufficient evidence', not zero), and "
        "flags what the professor should check.",
        "the Coordinator's propose_rubric_assessment",
        (
            Tool(
                "get_evidence",
                "Fetches the full bundle of one Research run, when the Judge wants to cite a "
                "passage. The opening message already summarises every run.",
                "a Research run ID",
                "the answer assessment, citations with passage IDs, conflicts and gaps",
                "An unknown run ID is refused.",
                JUDGE,
                ("judge.get_evidence",),
            ),
            Tool(
                "get_contributions",
                "Fetches the named students' own turns, each with the turn before it (usually "
                "the question), for students whose turns didn't fit in the opening message.",
                "1-50 student IDs",
                "each student's own turns (at most 20) and uncertain turns that might be theirs",
                "Unknown students are refused. Uncertain turns can never establish a score.",
                JUDGE,
                ("judge.contribution", "judge.get_contributions"),
            ),
            Tool(
                "score_contribution",
                "Saves findings for one or many students: for each criterion a score or "
                "'insufficient evidence', the turns it rests on, a justification, a confidence "
                "and an optional flag for the professor. The run ends once every student has "
                "a finding for every criterion.",
                "students, each with one entry per criterion",
                "who was saved, who was refused and why, and who is still to score",
                "Each student goes through validate_proposal: one who breaks a rule is refused "
                "with the reason and the others are still saved. Low confidence and flags "
                "become notes the professor sees.",
                JUDGE,
                ("judge.save", "judge.score_contribution"),
            ),
        ),
        code=(
            Snippet(
                "Its prompt",
                JUDGE,
                ("JUDGE_INSTRUCTIONS",),
                "Usually scores at once from the opening message, which already holds the "
                "rubric, each student's turns and a summary of Research's evidence.",
            ),
            Snippet(
                "A revision re-scores only what the audit objected to",
                JUDGE,
                ("revision_targets",),
                "Students the Auditor raised support, attribution, contradiction or uncertainty "
                "issues about are re-scored; everyone else's findings are kept.",
            ),
        ),
    ),
    Agent(
        "Feedback writer",
        "model call",
        "from Le Yong's workflow",
        "One structured model call per student: what went well and one next step, citing "
        "their own turns. It can ask for more evidence instead.",
        "the Coordinator's draft_student_feedback",
        code=(
            Snippet(
                "Its prompt and what it's given",
                "src/classpartai/participation/roles.py",
                ("feedback_for",),
                "Only that student's findings and turns, the rubric, goals and validated "
                "evidence. It writes strengths and one next step, never names another student.",
            ),
            Snippet(
                "The rules every model role gets",
                "src/classpartai/participation/roles.py",
                ("ROLE_POLICY",),
                "Everything it reads is untrusted data, never instructions; it may not send.",
            ),
        ),
    ),
    Agent(
        "Listener",
        "pipeline",
        "Tina (pipeline); line and turn checks by QJ",
        "Fixed steps, no model deciding anything: Whisper transcribes, pyannote splits the "
        "audio by voice, voice embeddings name each speaker, then each line and each turn is "
        "checked again and screened for words aimed at the grader. A person confirms in "
        "② Who spoke?.",
        "① Record (before the Coordinator runs)",
        code=(
            Snippet(
                "Tina's pipeline: transcribe, diarise, identify",
                "audio-service/pipeline.py",
                ("process_audio",),
                "Whisper, then pyannote, then a voice match per diarised speaker.",
            ),
            Snippet(
                "Who said what: words to turns, then the line and turn checks",
                "src/classpartai/agents/listener.py",
                ("decide_speakers",),
                "See 'How the Listener decides who spoke' below for each stage.",
            ),
            Snippet(
                "Injection screen: flag words aimed at the grader",
                "src/classpartai/agents/listener.py",
                ("screen_injection",),
                "Runs over every student or uncertain turn. The flag rides on the turn to the "
                "professor's review, the Judge and the Auditor; the words are never changed.",
            ),
        ),
    ),
    Agent(
        "Delivery",
        "code",
        "QJ",
        "Plain code, not a model: emails each student their approved feedback through "
        "AgentMail. Test mode sends everything to one inbox.",
        "the professor's Send button in ⑤",
        code=(
            Snippet(
                "The email: a fixed template, no model",
                "src/classpartai/participation/delivery.py",
                ("feedback_email",),
                "The Feedback writer's two paragraphs, the score, limitations and exact course "
                "excerpts, in a fixed layout.",
            ),
            Snippet(
                "Sending: only the approved version",
                "src/classpartai/participation/delivery.py",
                ("deliver_approved",),
                "Refuses unless the approval matches the exact content and recipients, and "
                "never retries an email whose outcome is unknown.",
            ),
        ),
    ),
]


def _find(tree: ast.Module, name: str) -> ast.stmt | None:
    owner, _, member = name.rpartition(".")
    body = tree.body
    if owner:
        scope = (ast.ClassDef, ast.FunctionDef)  # a method, or a function defined inside another
        parent = next((n for n in body if isinstance(n, scope) and n.name == owner), None)
        body = parent.body if parent else []
    for node in body:
        if getattr(node, "name", None) == (member or name):
            return node
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(isinstance(t, ast.Name) and t.id == (member or name) for t in targets):
                return node
    return None


def _branch(function: ast.stmt, tool: str) -> ast.If | None:
    """The ``if call.name == "<tool>":`` branch inside ``function``."""
    for node in ast.walk(function):
        if (
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and isinstance(node.test.left, ast.Attribute)
            and node.test.left.attr == "name"
            and any(isinstance(c, ast.Constant) and c.value == tool for c in node.test.comparators)
        ):
            return node
    return None


def source(snippet: Snippet, root: Path = REPO_ROOT) -> tuple[str, int] | None:
    """The snippet's code (whole lines, with the comments just above each name) and its first
    line number, or None when the file or a name is missing."""
    path = root / snippet.path
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8")
    lines, tree = text.splitlines(), ast.parse(text)
    parts, first = [], None
    for name in snippet.names:
        name, _, tool = name.partition("#")
        node = _find(tree, name)
        if node is not None and tool:
            branch = _branch(node, tool)
            if branch is None:
                return None
            # Only this branch: up to its last statement, not the elif chain after it.
            node, end = branch, branch.body[-1].end_lineno
        elif node is not None:
            end = node.end_lineno
        if node is None:
            return None
        start = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))])
        while start > 1 and lines[start - 2].lstrip().startswith("#"):
            start -= 1
        block = lines[start - 1 : end]
        indent = min(len(line) - len(line.lstrip()) for line in block if line.strip())
        parts.append("\n".join(line[indent:] for line in block))
        first = first or start
    return "\n\n".join(parts), first
