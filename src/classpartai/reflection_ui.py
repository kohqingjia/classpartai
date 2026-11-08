"""Reflection & risks: the page the project is presented from (there are no slides).

What worked and why, what did not and why, where it goes next, and what could go wrong with the
mitigation for each. Numbers come from committed results in eval/results or from the code, and
each says where.
"""

import streamlit as st

WORKED = [
    (
        "Checking each line against its own voice, not only its speaker",
        "Whisper's segments often run across a change of speaker, so words were credited to "
        "the wrong person. Aligning words to speaker turns and vetoing a line whose own "
        "voice names someone else cut the students' speech credited to the professor from "
        "7.6 s to 0.1 s (`eval/results/listener-20261107-synthetic-prof.md`).",
        "A wrong name on a score is worse than no name, so the Listener abstains "
        "(`ambiguous`) instead of guessing, and an uncertain line can never set a score.",
    ),
    (
        "Agentic retrieval that checks its own claims",
        "On 20 labelled answers the Research agent was right 94% of the time against 88% for "
        "single-pass RAG, and checked claims the single pass left unverified, at about six "
        "times the cost (US$0.025 vs US$0.004 an answer; "
        "`eval/results/research-is469-library.md`).",
        "A grade follows from it, so the extra cost is worth it here; it would not be for a "
        "chat answer. This is the course's own test: agentic RAG has to earn its cost.",
    ),
    (
        "Code is the authority, the model proposes",
        "Every score is rejected unless it cites the student's own turns and sits in the "
        "rubric's range; the model is told why and corrects it. Only an exact approved "
        "version can be sent, and no model has a send tool.",
        "Models are persuasive when wrong. Rules that cannot be argued with turn a model's "
        "mistake into a refusal the professor never sees.",
    ),
    (
        "Screening for injected instructions at the earliest stage",
        "The Listener now flags a line that tries to instruct the grader, before any agent "
        "reads it. On 40 labelled lines it catches 20 of 20 attacks with one false alarm on 20 "
        "ordinary lines (`eval/results/injection-*.md`, `eval/injection_eval.py`).",
        "Catching it once, first, means the Judge is told, the professor sees it while "
        "checking the transcript, and the Auditor does not need to guess again. "
        "**Caveat:** we wrote the attacks and the pattern together, so 20/20 is "
        "an upper bound, not a held-out result.",
    ),
    (
        "Fewer model calls where the work is routine",
        "The Judge scores every student in one call (about one model call a run). On the "
        "scripted whole-workflow the Judge optimisation alone took 22 model calls to 15. "
        "Every other agent keeps its own decisions: we cut calls where one agent was being "
        "asked a question per student, not by taking a decision away from an agent.",
        "Calls were counted by the usage ledger on scripted runs, not on a live model: the "
        "live saving is not measured yet.",
    ),
]

DID_NOT = [
    (
        "Research is the slowest part of a run",
        "An answer takes about 113 s and US$0.025 against 22 s and US$0.004 for single-pass "
        "RAG. That is the price of the 6 extra points of correctness above, not a reason to "
        "drop it.",
        "Where the time goes is measured, so it can be cut without removing the checking: "
        "a lower reasoning effort is run as an experiment (Experiments tab) and judged on "
        "quality before it is adopted.",
    ),
    (
        "The Judge agrees with people on reasoning but less on engagement",
        "Against 20 reviewed labels (37 scores) the Judge's weighted kappa is 0.60 overall and "
        "91.9% of its scores are within one point of the human score. On reasoning it is "
        "0.87; on engagement it is only 0.26, and 40.5% of all scores match exactly "
        "(`eval/results/judge-20261108-150050.json`).",
        "Engagement is the vaguer criterion, so people and the Judge disagree about it more. "
        "One person wrote the key, so the numbers measure agreement with that person.",
    ),
]

FUTURE = [
    "**Compare Judges.** Run the single-call Judge, the tool-using Judge and a smaller model "
    "against the same reviewed key, on agreement with people and cost per point of "
    "agreement; have a second person score part of the key.",
    "**A model-based injection check** as a second Listener step, evaluated with a held-out "
    "set of attacks the pattern author has not seen.",
    "**Real classroom audio.** Every recording so far is scripted with synthetic or cloned "
    "voices; noise, overlap and accents are untested.",
    "**Long recordings in segments.** A three-hour lesson exceeds one run's budget and stops "
    "cleanly with no draft; assessing it by segment would fix that.",
    "**Let the professor move a line to the right speaker** in step 2, not only confirm.",
    "**Student history.** A third Judge tool, `get_student_history`, so a score can consider "
    "earlier sessions (and consistency across sessions can be measured).",
]

RISKS = [
    (
        "Prompt injection: a student speaks to the grader",
        "A transcript is untrusted text anyone in the room can add to.",
        "The Listener screens every turn and flags it; the Judge is told and scores the "
        "content only; the Auditor trusts the flag and scans the Judge's rationale and cited "
        "course text; all model input is passed as data, never as instructions.",
        "A pattern is a heuristic and English only; a rephrased attack can pass it.",
    ),
    (
        "Wrong speaker credited with a score",
        "Voice matching is imperfect and similar voices can merge.",
        "Best match must pass a score and a margin; each line and each whole turn is checked "
        "again; unsure lines stay `uncertain` and never set a score; the professor confirms "
        "before anything is scored.",
        "25 of 26 student lines right on synthetic demos, none credited to the wrong student; "
        "accents and similar voices untested.",
    ),
    (
        "A score that is not supported by evidence",
        "A model can sound sure and be wrong.",
        "Scores must cite the student's own turns and sit inside the range; citations must be "
        "exact excerpts; “insufficient evidence” is never a zero; the Auditor raises issues "
        "and can ask for one re-score but never lowers a score itself.",
        "How closely scores follow a person's is not yet measured.",
    ),
    (
        "Unfairness to quiet students or to a way of speaking",
        "A participation score can reward fluency or loudness.",
        "Silence gives “no observed contribution”, never a poor-understanding claim; the name "
        "swap guardrail checks the same words get the same score; the Auditor looks at "
        "score against speaking time.",
        "No fairness measurement on real students or across accents.",
    ),
    (
        "Student data leaves the room",
        "Voices, names and transcripts are personal data, and the transcript goes to the "
        "model provider.",
        "Feedback cannot name another student; emails go only to the roster's own addresses; "
        "test mode sends to one inbox.",
        "No login on the app, no retention policy, and the provider still receives "
        "transcripts. Consent for the demo voices is the team's own.",
    ),
    (
        "Feedback sent by mistake or twice",
        "An email cannot be taken back.",
        "No model has a send tool; approval is tied to the exact content and recipients by a "
        "digest and breaks on any edit; one delivery per student; an unclear outcome is never "
        "retried automatically.",
        "A professor can still approve a bad draft; the tool warns, it does not stop them.",
    ),
    (
        "Runaway cost or time",
        "Agents loop and reasoning models bill hidden tokens.",
        "One shared budget of calls, tokens and seconds across all agents; a refusal cap; "
        "every call recorded with its cost on the Monitoring page.",
        "Prices on that page are an unverified draft; the live cost after the savings is "
        "not measured.",
    ),
    (
        "Provider outage or rate limit",
        "The workflow depends on an outside model.",
        "A failure ends the run safely as “needs review” with a reason, never a made-up "
        "result; nothing is sent.",
        "No second provider to fall back to.",
    ),
    (
        "Over-trusting the automation",
        "A fluent draft invites a quick approve.",
        "Scores are labelled provisional; open issues must be acknowledged with a reason; "
        "approval is a separate step from the audit.",
        "Whether professors read the drafts closely is a human question this project did not test.",
    ),
]


def _md(text: str) -> None:
    """st.markdown with "$" kept as a dollar sign (Streamlit reads "$...$" as LaTeX)."""
    st.markdown(text.replace("$", "\\$"))


def _entries(items, colour: str) -> None:
    for title, what, why in items:
        with st.container(border=True):
            _md(f":{colour}[**{title}**]")
            _md(what)
            _md(f"**Why:** {why}")


def render() -> None:
    st.title("Reflection & risks")
    st.header(":green[What worked, and why]")
    _entries(WORKED, "green")
    st.header(":orange[What did not, and why]")
    _entries(DID_NOT, "orange")
    st.header(":blue[Where it goes next]")
    _md("\n".join(f"- {item}" for item in FUTURE))
    st.header(":red[Risks and how we handle them]")
    st.caption(
        "Each mitigation is enforced in code unless it says otherwise. Residual = what is left."
    )
    for risk, why, mitigation, residual in RISKS:
        with st.container(border=True):
            _md(f":red[**{risk}**] · {why}")
            _md(f":green[**Mitigation**] · {mitigation}")
            _md(f":orange[**Residual**] · {residual}")
