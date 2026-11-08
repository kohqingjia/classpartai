"""How it works: the agentic controls the system enforces.

The mapping to the course's terms, the project brief and the reasons the system is agentic are in
demo_points.md; what worked and what did not is on the Reflection & risks page.
"""

import streamlit as st

# The six controls for agents (slide 57): each, and where it is enforced
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


def _table(header: tuple[str, ...], rows) -> str:
    out = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    out += ["| " + " | ".join(cell.replace("|", "/") for cell in row) + " |" for row in rows]
    return "\n".join(out)


def render() -> None:
    st.subheader("Agentic controls: the six controls for agents, and the lethal trifecta")
    st.markdown(_table(("Control", "Where ClassPart AI enforces it"), SIX_CONTROLS))
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
