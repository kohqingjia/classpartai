"""③ Judge: score a contribution against the CP rubric (LLM-as-judge).

PLACEHOLDER until the Judge agent is built. It returns a neutral 3/5 on every criterion so
the rest of the pipeline has something to work with. Keep the signature and return type.
"""

from classpartai.contracts import Contribution, CriterionScore, Judgement, Research

IS_PLACEHOLDER = True

RUBRIC = ["relevance", "accuracy", "depth", "builds on others"]


def judge(contribution: Contribution, research: Research) -> Judgement:
    note = "Placeholder score until the Judge agent is built."
    return Judgement(
        scores=[CriterionScore(criterion=c, score=3, rationale=note) for c in RUBRIC],
        overall=3.0,
        rationale=note,
        confidence=0.0,
    )
