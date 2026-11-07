"""Reflection & risks: the page the project is presented from (there are no slides).

What worked and why, what did not and why, where it goes next, and what could go wrong with the
mitigation for each. Numbers come from committed results in eval/results or from the code, and
each says where. Nothing here is a claim about live model behaviour that has not been run.
"""

import json
from pathlib import Path

import streamlit as st

from classpartai.config import REPO_ROOT

RESULTS = REPO_ROOT / "eval" / "results"

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
        "reads it. On 40 labelled lines the first pattern caught 7 of 20 attacks; the widened "
        "one catches 20 of 20 with one false alarm on 20 ordinary lines "
        "(`eval/results/injection-*.md`, `eval/injection_eval.py`).",
        "Catching it once, first, means the Judge is told, the professor sees it while "
        "checking the transcript, and the Auditor does not need to guess again. "
        "**Caveat:** we wrote the attacks and the pattern together, so 20/20 is "
        "an upper bound, not a held-out result.",
    ),
    (
        "Fewer model calls where the work is routine",
        "The Judge scores every student in one call (about one model call a run). A student "
        "with no observed turns gets fixed wording with no model call. One Coordinator action "
        "drafts everyone's feedback. The Coordinator and the Feedback writer think at a low "
        "setting. On the scripted whole-workflow the Judge optimisation alone took 22 model "
        "calls to 15.",
        "Calls were counted by the usage ledger on scripted runs, not on a live model: the "
        "live saving is not measured yet.",
    ),
]

DID_NOT = [
    (
        "Agentic RAG is slow and costly for what it adds",
        "About 113 s and US$0.025 an answer against 22 s and US$0.004, for 6 points of "
        "correctness. It still searched the course for the two answers that needed no "
        "evidence.",
        "The agent is not taught when not to look. A cheap pre-check for answers with no claim "
        "to verify is the next saving.",
    ),
    (
        "Research's “answers the question” score is 35%",
        "Our labels say a wrong answer still answers the question; the agent's definition "
        "says a wrong answer covers no expected points, so it says no.",
        "The metric and the labels disagree. The number measures our definition, not the "
        "agent; we fix the definition before we trust the number.",
    ),
    (
        "The guardrail suite is not stable between runs",
        "Cases 05 (name swap) and 06 (uncertain speaker) failed in one run and passed in "
        "another: 8/10, then 10/10.",
        "Model output varies. One run cannot support a claim, so results need repeats and a range.",
    ),
    (
        "The first injection pattern missed most phrasings",
        "It caught 7 of 20, missing “disregard the previous instructions” and “forget "
        "everything above”.",
        "A fixed list of phrases reflects the phrases its author thought of. Real students "
        "(and Whisper) say it differently.",
    ),
    (
        "The Judge's agreement with people is not measured",
        "The harness and 20 labels exist; the labels are a draft nobody has reviewed and the "
        "Judge has not been run against them.",
        "Until two people agree on the key, a high or low kappa would measure our draft, "
        "not the Judge.",
    ),
]

FUTURE = [
    "**Measure the Judge.** Review the answer key as a team, then compare the single-call "
    "Judge, the tool-using Judge, and a smaller model, on agreement with people and cost per "
    "point of agreement.",
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
        "the data download page needs a password set on the server; test mode sends to one "
        "inbox.",
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


def _latest(pattern: str) -> dict | None:
    found = sorted(RESULTS.glob(pattern))
    return json.loads(Path(found[-1]).read_text(encoding="utf-8")) if found else None


def _entries(items, colour: str) -> None:
    for title, what, why in items:
        with st.container(border=True):
            st.markdown(f":{colour}[**{title}**]")
            st.markdown(what)
            st.markdown(f"**Why:** {why}")


def render() -> None:
    st.title("Reflection & risks")
    st.markdown(
        '<p class="muted">What worked and why, what did not and why, where it goes next, and '
        "what could go wrong. Every number names the result it comes from. Nothing here was "
        "measured on a live model unless it says so.</p>",
        unsafe_allow_html=True,
    )
    injection = _latest("injection-*.json")
    if injection:
        first, wide = injection["first pattern"], injection["widened pattern"]
        cols = st.columns(3)
        cols[0].metric("Injection attacks caught", f"{wide['caught']}/{wide['attacks']}")
        cols[1].metric("Before the fix", f"{first['caught']}/{first['attacks']}")
        cols[2].metric("False alarms", len(wide["false_alarms"]))

    st.header(":green[What worked, and why]")
    _entries(WORKED, "green")
    st.header(":orange[What did not, and why]")
    _entries(DID_NOT, "orange")
    st.header(":blue[Where it goes next]")
    st.markdown("\n".join(f"- {item}" for item in FUTURE))
    st.header(":red[Risks and how we handle them]")
    st.caption(
        "Each mitigation is enforced in code unless it says otherwise. Residual = what is left."
    )
    for risk, why, mitigation, residual in RISKS:
        with st.container(border=True):
            st.markdown(f":red[**{risk}**] · {why}")
            st.markdown(f":green[**Mitigation**] · {mitigation}")
            st.markdown(f":orange[**Residual**] · {residual}")
