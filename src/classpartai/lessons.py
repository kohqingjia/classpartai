"""What the checks have learnt about an agent's mistakes in this session.

An evaluation that only reports a failure does not stop the next one. Here every check of an
agent's output that finds a problem leaves a *lesson* (which agent, which rule, what to do
instead), kept with the session. The next time that agent is called in the session, the lessons
are put in its opening message as ``earlierChecks``, so the second student's email does not
repeat the first student's mistake, and a re-score or a second audit starts knowing what was
refused before.

Who writes lessons: the Feedback checks (``feedback_checks.py``), the Judge when a score is
refused by the rules, and the Auditor when one of its tool calls is refused. A lesson repeated
is counted, not duplicated. Lessons never carry what students said, only the rule and the advice.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Lesson:
    agent: str
    rule: str
    advice: str


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "rule"


class Lessons:
    """The session's lessons: in the database when there is one, in memory otherwise."""

    def __init__(self, records=None, session_id: str | None = None):
        self.records, self.session_id = records, session_id
        self.memory: dict[tuple[str, str], dict] = {}

    def note(self, agent: str, rule: str, advice: str) -> None:
        if self.records is not None and self.session_id:
            self.records.note_lesson(self.session_id, agent, rule, advice)
            return
        entry = self.memory.setdefault((agent, rule), {"advice": advice, "times": 0})
        entry["times"] += 1

    def for_agent(self, agent: str, limit: int = 8) -> list[dict]:
        """The agent's lessons, most repeated first, as the agent will read them."""
        if self.records is not None and self.session_id:
            rows = self.records.lessons(self.session_id, agent)
        else:
            rows = [
                {"rule": rule, **entry}
                for (who, rule), entry in self.memory.items()
                if who == agent
            ]
        rows.sort(key=lambda r: -r["times"])
        return [
            {"rule": r["rule"], "advice": r["advice"], "times": r["times"]} for r in rows[:limit]
        ]


EARLIER_CHECKS = (
    " `earlierChecks`, when present, lists mistakes that checks found in your earlier work in this "
    "session. Do not repeat them."
)
