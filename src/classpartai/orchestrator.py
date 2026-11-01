"""Runs the stages in order and assembles one class session's results for the Action agent."""

from classpartai.agents import auditor, judge, research
from classpartai.contracts import Contribution, Research, ScoredContribution, SessionResults

STAGES = {"research": research, "judge": judge, "auditor": auditor}


def score_session(
    contributions: list[Contribution], session_id: str, course: str, date: str, topic: str = ""
) -> SessionResults:
    """Research, judge and audit every contribution that can be credited to a known student."""
    items = []
    for c in contributions:
        if c.person_id is None or not c.substantive:
            items.append(ScoredContribution(contribution=c, research=Research(route="none")))
            continue
        found = research.research(c, topic)
        judgement = judge.judge(c, found)
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
