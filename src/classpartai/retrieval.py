"""What an evidence agent retrieved, for the UI's vault view.

Both evidence agents record their course searches, in different shapes: Research
(research/bridge.py) keeps ``searches`` (query + passages returned, with scores); the course
evidence agent (evidence.py) keeps an action per ``search_course_passages`` call whose
``resultReferences`` are the passages returned. ``searches_of`` reads either, from a live
progress object or a saved run's progress dict.
"""

import json


def _get(progress, key: str, default=None):
    if isinstance(progress, dict):
        return progress.get(key, default)
    return getattr(progress, key, default)


def searches_of(progress) -> list[dict]:
    """[{"query": str, "hits": [{"passageId": str, "score": float | None}]}], in order."""
    searches = _get(progress, "searches")
    if searches is not None:
        return list(searches)
    out = []
    for action in _get(progress, "actions", []) or []:
        if action["tool"] != "search_course_passages" or action["outcome"] != "ok":
            continue
        try:
            query = str(json.loads(action["arguments"]).get("query", ""))
        except (ValueError, AttributeError):
            query = ""
        hits = [{"passageId": r, "score": None} for r in action.get("resultReferences", [])]
        out.append({"query": query[:300], "hits": hits})
    return out


def examined_of(progress) -> list[str]:
    """Passages Research graded against a claim (the course agent doesn't grade)."""
    seen = []
    for pack in _get(progress, "research", None) or []:
        for claim in pack.get("claims", []):
            for ev in claim.get("evidence", []):
                pid = (ev.get("chunk_id") or "").rsplit("#", 1)[0]
                if pid and pid not in seen:
                    seen.append(pid)
    return seen
