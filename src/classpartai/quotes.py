"""Show what a student said instead of a turn ID.

The Judge and the Feedback writer cite turns by ID (``turn-002``), because validation checks
those IDs. People can't read IDs, so on screen and in the email each ID becomes a short quote
of that turn. The stored draft keeps the IDs.

The professor's views quote any turn. A student's feedback quotes only that student's own
turns (``own_turns``): another student's turn ID stays an ID, so nobody is shown what a
classmate said.
"""

import html
import re
from collections.abc import Iterable

from classpartai.assessment import AssessmentInputs

EXCERPT_CHARS = 110
QUOTE_COLOUR = "#7fb4ec"  # the student's own words, on every page that shows them


class Plain(str):
    """A replacement shown as it is, not as a quote."""


def own_turns(inputs: AssessmentInputs, student_id: str) -> dict[str, str]:
    """What a student may see quoted in their own feedback: only their own turns. A turn that
    names another roster student is shown by its time instead, so no one else's identity leaks
    (the same rule validate_proposal applies to the feedback text)."""
    others = [o for o in inputs.roster if o.id != student_id]
    out: dict[str, str] = {}
    for t in inputs.transcript.turns:
        if t.speaker.kind != "student" or t.speaker.studentId != student_id:
            continue
        # Compared the way the quote is shown: whitespace collapsed, so a name split across a
        # line break ("Priya\nNair") is still caught.
        text = " ".join(t.text.split()).lower()
        names = [" ".join(n.split()).lower() for o in others for n in (o.displayName, o.id)]
        if any(n in text for n in names):
            minutes, seconds = divmod(t.startMs // 1000, 60)
            out[t.id] = Plain(f"your comment at {minutes}:{seconds:02d}")
        else:
            out[t.id] = t.text
    return out


def _shown(said: str) -> str:
    return said if isinstance(said, Plain) else f"“{excerpt(said)}”"


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",.;:") + "…"


def _pattern(ids: Iterable[str]) -> re.Pattern | None:
    ids = sorted({i for i in ids if i}, key=len, reverse=True)  # longest first: turn-10 › turn-1
    if not ids:
        return None
    return re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, ids)) + r")(?![\w-])")


def quote_plain(text: str, turns: dict[str, str]) -> str:
    """``turns`` maps a turn ID to what was said. Unknown IDs are left as they are."""
    pattern = _pattern(turns)
    if pattern is None:
        return text
    return pattern.sub(lambda m: _shown(turns[m.group(1)]), text)


def quote_html(text: str, turns: dict[str, str]) -> str:
    """Like ``quote_plain``, but escaped for st.markdown, each quote coloured, its ID on hover."""
    pattern = _pattern(turns)
    if pattern is None:
        return html.escape(text).replace("$", "&#36;")
    out, last = [], 0
    for m in pattern.finditer(text):
        out.append(html.escape(text[last : m.start()]))
        tid = m.group(1)
        out.append(
            f'<span style="color:{QUOTE_COLOUR}" title="{html.escape(tid)}">'
            f"{html.escape(_shown(turns[tid]))}</span>"
        )
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out).replace("$", "&#36;")  # a "$" would start LaTeX in st.markdown
