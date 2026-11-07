"""A pattern check for words aimed at the grader ("ignore the rubric", "give me full marks").

The Listener runs it over every turn it transcribes, so the professor sees a flag while reviewing
the transcript and the Judge is told which turns try to instruct it. The Auditor runs the same
check over the Judge's rationales and over cited course text, where it is a deterministic
guardrail rather than a tool the model chooses to call.

It is a heuristic, English only: a miss is not proof of safety, and the flag never changes the
transcript text. eval/injection_eval.py measures its precision and recall on a labelled set.
"""

import re

SUSPECTED = "suspected_instruction"
BENIGN = "benign_quoted_example"
NONE = "no_pattern_detected"

# Words aimed at the grader, in four families. Spoken text is looser than typed text, so the
# patterns allow a few filler words between a verb and what it is aimed at.
_FILLER = r"\s+(?:\w+\s+){0,3}"
_TARGET = (
    r"(?:instructions?|rubric|rules|guidelines|criteria|marking scheme|prompt|directions"
    r"|everything (?:above|before|so far)|what you were told)"
)
_ROLE = r"(?:grader|marker|judge|professor|teacher|examiner|auditor|assistant|ai)"
_TOP = (
    r"(?:full|maximum|max|top|perfect|highest|best|5\s*/\s*5|10\s*/\s*10|100\s*%"
    r"|(?:5|five) out of (?:5|five)|(?:10|ten) out of (?:10|ten))"
)
_PATTERN = re.compile(
    "|".join(
        [
            # 1. "ignore / disregard / forget the rubric", "ignore everything above"
            rf"\b(?:ignore|disregard|forget|bypass|skip|discard|override){_FILLER}{_TARGET}",
            # 2. asking for a score: "give me full marks", "score me 5 out of 5"
            rf"\b(?:give|award|grant|assign|mark|score|rate|grade)\s+(?:me|us|this student"
            rf"|this (?:answer|response|one)|my (?:answer|response)|him|her|them)\b{_FILLER}"
            rf"{_TOP}",
            r"\b(?:full|maximum|perfect|top) (?:marks|score|credit|points|grade)\b"
            r"(?=.{0,40}\b(?:please|give|award|should|must|deserve))",
            r"\b(?:override|change|raise|set) (?:the |my |this )?(?:grade|score|mark)\b",
            # 3. telling the grader who it is, or what to do: "you are now the grader",
            #    "as the grader you should", "pretend you are the professor", "act as the judge"
            rf"\byou are (?:now |no longer )?(?:the |a |an )?{_ROLE}\b",
            rf"\b(?:act|behave|respond|answer) as (?:the |a |an )?{_ROLE}\b",
            r"\bpretend (?:that )?(?:you are|to be|you're)\b",
            rf"\bas (?:the|a|an) {_ROLE},? you (?:should|must|will|need to|have to)\b",
            # 4. reaching for the prompt itself
            r"\b(?:system|developer|hidden) (?:prompt|message|instructions?)\b",
            r"\bnew instructions?\b",
            r"\b(?:reveal|repeat|show|print) (?:your |the )?(?:prompt|instructions)\b",
        ]
    ),
    re.I | re.S,
)


def injection_signal(original: str) -> dict:
    """Classify ``original``: suspected instruction, benign quoted example, or nothing found."""
    matches = list(_PATTERN.finditer(original))
    # Narrow contextual heuristic: quoted commands explicitly discussed as an attack/example.
    # Mixed text with an instruction outside quotes remains suspicious. Not a security proof.
    quoted = [(m.start(), m.end()) for m in re.finditer(r'"[^"\n]*"|“[^”\n]*”', original)]
    teaching = bool(re.search(r"example|quoted|injection|attack|do not follow", original, re.I))
    benign = (
        bool(matches)
        and teaching
        and all(any(a <= m.start() and m.end() <= b for a, b in quoted) for m in matches)
    )
    return {
        "classification": BENIGN if benign else SUSPECTED if matches else NONE,
        "original_text": original,
        "sanitised_view": None,
        "limitation": "Heuristic suspicion only; no pattern is not proof of safety",
    }
