"""How it works: the system in the course's own words, the project brief it answers, and what
we learnt building it.

Every term is quoted from the IS469 slides (topic and slide number in brackets), and every claim
points at something in this repository, so the page can be presented and checked.
"""

import streamlit as st

from classpartai.ui import log_tag

# (part, what it does here, the course's term for it)
TOPIC_ROWS = [
    (
        "Listener",
        "Whisper `base`, an encoder-decoder transformer, int8-quantised on CPU and decoded with "
        "beam search (5 beams); pyannote splits the voices; ECAPA voice embeddings compared by "
        "cosine similarity, named only above 0.35 and 0.10 clear of the runner-up; each line "
        "screened for words aimed at the grader",
        '2 · "Encoder", "Decoder" (S19); 5 · "Beam search" (S7); 4 · "Quantisation" '
        'int8 (S46); 1 · "Cosine similarity … measures the angle, not the magnitude" (S30)',
    ),
    (
        "Coordinator",
        "A model in a loop with six tools and a stop condition; it calls Research, the Judge "
        "and the Auditor as tools; one budget for everything (72 model calls, 400k tokens, "
        "900 s); no approve or send tool",
        '7 · "an agent = an LLM … + a harness" (S3); "Perceive → Plan → Act → Observe" '
        '(S13); "The supervisor pattern" (S47); "human-in-the-loop checkpoints" (S48)',
    ),
    (
        "Research",
        "Routes to the course notes, the web or nowhere; hybrid search: BM25 and embeddings "
        "fused with RRF (k = 60); grades what it finds and rewrites the query when evidence is "
        "weak, at most twice; cites only verbatim quotes",
        '8 · "Agentic RAG makes retrieval a TOOL" (S44); "Plan → Search → Judge → Re-query → '
        'Answer" (S47); "Routing", "Self-correction (CRAG …)" (S48); "Hybrid search", '
        '"Query rewriting" (S39); "Rank fusion (RRF)" (S37); "Grounding rule" (S42)',
    ),
    (
        "Judge",
        "Scores each student on an explicit rubric with three tools; every score passes "
        "deterministic checks before it is saved; confidence and flags for the professor; a "
        "separate reasoning-effort setting (`JUDGE_REASONING_EFFORT`)",
        '6 · "LLM-as-judge" with an "explicit rubric" (S68); "Verify first, judge only what '
        'you can\'t check" (S66); 7 · "effort / thinking dial" (S41)',
    ),
    (
        "Auditor",
        "A second agent that checks the Judge with six read-only tools: compares similar "
        "answers, verifies every citation, checks scores against speaking time, can ask for one "
        "re-score, never changes a score; the Listener's injection flag and a rationale aimed "
        "at the grader are checked before the model runs",
        '6 · "programmatic check → verifiable reward → LLM-judge → human" (S66); 7 · '
        '"Reflexion & self-critique", "Verify-then-continue" (S37)',
    ),
    (
        "Feedback writer",
        "One structured model call per student, then rule checks (no classmate named, silence "
        "described as not observed, no judgement of ability); a broken rule is sent back once "
        "and becomes a lesson for the next email. Deliberately not an agent: it needs no tools",
        '7 · "Teardown test: a single … call behind a nice UI is NOT an agent" (S63)',
    ),
    (
        "Approve and send",
        "The professor approves one exact version (SHA-256 of content and recipients); code, "
        "not a model, sends it",
        '9 · "Excessive agency" (S48); "Six controls for agents" (S57, below)',
    ),
    (
        "Monitoring and evals",
        "Every model call's tokens, latency and cost, and a trace of every step; eval scripts "
        "for each agent",
        '7 · "Evaluate the trajectory" (S54), "Observability & tracing" (S57); 6 · "treat '
        'evaluation as a first-class artifact" (S76)',
    ),
]

# Topic 9, slide 57: each control and where it is enforced
SIX_CONTROLS = [
    (
        "Allow-list",
        "Email goes only to roster-managed recipients; test mode sends every email "
        "to one inbox instead",
    ),
    ("Own identity", "Mail is sent from the project's own AgentMail inbox, not a person's account"),
    (
        "Approval",
        "Nothing is sent until the professor approves that exact version; any edit "
        "cancels the approval",
    ),
    (
        "Full log",
        "Every model call, tool call and delivery attempt is stored (Monitoring, run "
        "replays, delivery states)",
    ),
    (
        "Limits and stop",
        "One budget per run; an email whose outcome is unknown is never retried automatically",
    ),
    (
        "Distrust inputs",
        "Transcripts, slides and tool results are wrapped as untrusted data; "
        "the Research and Auditor agents flag text that tries to instruct the grader",
    ),
]

BRIEF_ROWS = [
    (
        "Integrates at least two substantial topics",
        "Six: transformers (2), evaluation (5-6), agents and harness (7), agentic RAG (8), "
        "ethics and guardrails (9), embeddings (1). See the table above",
    ),
    (
        "End-to-end implementation with an evaluation pipeline",
        "Recording → transcript → assessment → approval → email, in this app; `eval/` scripts "
        "for the Listener, Research, Judge, guardrails and cost",
    ),
    (
        "Evidence of debugging and validation",
        'Hundreds of automated tests on every pull request; the fixes listed under "What did '
        'not" below, each with a regression test',
    ),
    (
        "Quantitative metrics",
        "Listener: wrong-speaker lines, word error rate. Research: correctness, context "
        "precision. Guardrails: attacks caught. Cost and latency per run. Task success of the "
        "seven demo runs. See Evaluation",
    ),
    (
        "Qualitative analysis",
        "Seven demo seminars in our own voices: everyone takes part, a silent student, nobody "
        "answers, a wrong claim, a student gaming the grader, one student dominating, a guest",
    ),
    (
        "Compares at least two alternatives",
        "Single-pass RAG vs the Research agent; Listener before and after its fixes; Auditor "
        "tool descriptions, one change at a time; the software against a teaching assistant",
    ),
    ("Reflection, and a direction for future work", '"What worked, what did not" below'),
    ("Risks and mitigations", "Guardrails, the six controls and the lethal trifecta, below"),
    (
        "Reproducible: repository, README, seeds, config",
        "Public repository with a README; `SEED=42`; `.env.example`; every result in "
        "`eval/results` names the run that produced it",
    ),
    (
        "Good teamwork, not disparate pieces",
        "One workflow: Tina's Listener feeds the Coordinator Le Yong designed, which calls "
        "Tasmin's Research, Saurabh's Judge and Le Yong's Auditor",
    ),
]

WORKED = [
    "**Verify first, judge last.** Deterministic checks reject a score that cites someone "
    "else's turn or leaves the rubric's range, and the model is told why and corrects it.",
    "**The agent earns its cost.** Research's agent is right more often than single-pass RAG "
    "(94% vs 88%) for about six times the cost: worth it for something that affects a grade "
    '(Topic 8, S51: "agentic RAG has to earn its extra cost and latency").',
    '**Abstaining beats guessing.** Unclear voices stay "ambiguous" and silent students get '
    '"insufficient evidence", never a zero.',
    "**Guardrails held.** Ten adversarial cases, including injection, a poisoned course "
    'document and a name-swap fairness test (Topic 9, S13: "counterfactual test"), all '
    "caught.",
]

DID_NOT = [
    "**Short lines escaped the voice check.** The professor's tail was credited to a student "
    "because each piece was under a second. Fix: check the whole turn as well (Listener).",
    "**A re-run skipped the Judge.** The Coordinator reused the previous run's scores. Fix: "
    "every run must score before feedback, audit or review.",
    "**Refusals burnt the budget.** Notes over their length limit were refused and resent "
    "until the run ran out. Fix: shorten them instead.",
    "**The Coordinator's context filled up.** Whole drafts in every tool result hit the 100 KB "
    "history limit after seven steps. Fix: tool results now carry a summary.",
    "**An audit loop and an oversized fallback.** One bad issue ID refused the whole audit; "
    "the fallback audit sent 158 KB of course documents. Fix: ignore the bad ID; leave the "
    "documents out.",
    "Each of these was found by running the seven demos and reading the traces on the "
    'Monitoring page; after the fixes all seven reach "ready for professor review".',
]

STILL_OPEN = [
    "**The Judge's agreement with human scores is not measured yet.** The eval is built; the "
    "human labels are still drafts.",
    "**Long recordings.** A three-hour lesson would exceed one run's budget (the guardrail "
    "eval's 420-turn transcript stopped cleanly with no draft). Next: assess it in segments.",
    '**Research\'s "answers the question" is low (35%)**, because our labels and its '
    "definition disagree: a wrong answer still answers the question. Next: fix the "
    "definition or the labels.",
    "**Speakers can only be confirmed, not reassigned**, in ② Who spoke?. Next: let the "
    "professor move a line to the right person.",
    "**Why no fine-tuning (Topic 4).** Our gap is knowledge (the course notes), not behaviour, "
    'so retrieval fits better than fine-tuning: "Fine-tuning teaches a model how to behave, '
    'far more than what to know" (S6), and "Climb only as far as your evals force you to" '
    "(S4).",
]


def _table(header: tuple[str, ...], rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell.replace("|", "/") for cell in row) + " |" for row in rows]
    return "\n".join(out)


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items)


def render() -> None:
    st.subheader("Mapped to IS469, in the course's words")
    st.caption('Terms quoted from the slides: topic · "term" (slide).')
    # Each part's name in its agent's ink, as in the diagram above; parts that are not agents
    # stay grey
    rows = [(log_tag(part), what, term) for part, what, term in TOPIC_ROWS]
    st.markdown(_table(("Part", "What it does here", "Course term"), rows), unsafe_allow_html=True)

    st.subheader("Topic 9: the six controls for agents, and the lethal trifecta")
    st.markdown(_table(("Control (S57)", "Where ClassPart AI enforces it"), SIX_CONTROLS))
    st.markdown(
        "**The lethal trifecta** (S55) is private data, untrusted content and a way to send "
        "data out. ClassPart AI has the first two (students' contributions, and a transcript "
        "anyone in the room can speak into), so we limit the third. Email, the channel that "
        "reaches people, has a person in the chain: no model has a send tool, and only the "
        "professor's approval of an exact version releases one. Two channels remain and are "
        "named, not hidden: the model provider receives the transcript to do its work, and "
        "Research's web search (Tavily, on the live site) sends queries the model writes. "
        "Web results are never cited as evidence for a score."
    )

    st.subheader("How it meets the project brief")
    st.markdown(_table(("The brief asks for", "Where it is"), BRIEF_ROWS))

    st.subheader("What worked, what did not, and what's next")
    st.markdown("**Worked**\n\n" + _bullets(WORKED))
    st.markdown("**Did not, and how we fixed it**\n\n" + _bullets(DID_NOT))
    st.markdown("**Still open, and next**\n\n" + _bullets(STILL_OPEN))
