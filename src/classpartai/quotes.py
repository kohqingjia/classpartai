"""Show what a student said instead of a turn ID.

The Judge and the Feedback writer cite turns by ID (``turn-002``), because validation checks
those IDs. People can't read IDs, so on screen and in the email each ID becomes a short quote
of that turn. The stored draft keeps the IDs.
"""

import html
import re
from collections.abc import Iterable

EXCERPT_CHARS = 110
QUOTE_COLOUR = "#7fb4ec"  # the student's own words, on every page that shows them


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
    return pattern.sub(lambda m: f"“{excerpt(turns[m.group(1)])}”", text)


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
            f"“{html.escape(excerpt(turns[tid]))}”</span>"
        )
        last = m.end()
    out.append(html.escape(text[last:]))
    return "".join(out).replace("$", "&#36;")  # a "$" would start LaTeX in st.markdown
