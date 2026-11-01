"""Runs the stages in order and assembles one class session's results for the Action agent."""

from collections.abc import Callable

from classpartai.agents import auditor, judge, research
from classpartai.contracts import Contribution, Research, ScoredContribution, SessionResults

STAGES = {"research": research, "judge": judge, "auditor": auditor}


def score_session(
    contributions: list[Contribution],
    session_id: str,
    course: str,
    date: str,
    topic: str = "",
    progress: Callable[[str, int, int], None] | None = None,
) -> SessionResults:
    """Research, judge and audit every contribution that can be credited to a known student.

    ``progress(stage, n, total)`` is called as each stage starts on contribution n (1-based),
    so a UI can show the pipeline working.
    """
    report = progress or (lambda stage, n, total: None)
    items, total = [], len(contributions)
    for n, c in enumerate(contributions, start=1):
        if c.person_id is None or not c.substantive:
            items.append(ScoredContribution(contribution=c, research=Research(route="none")))
            continue
        report("research", n, total)
        found = research.research(c, topic)
        report("judge", n, total)
        judgement = judge.judge(c, found)
        report("auditor", n, total)
        items.append(
            ScoredContribution(
                contribution=c,
                research=found,
                judgement=judgement,
                audit=auditor.audit(c, judgement),
            )
        )
    return SessionResults(
        session_id=session_id,
        course=course,
        date=date,
        topic=topic,
        items=items,
        placeholder_stages=[name for name, mod in STAGES.items() if mod.IS_PLACEHOLDER],
    )
