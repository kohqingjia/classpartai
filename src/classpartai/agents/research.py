"""② Research (agentic RAG): find evidence to check a contribution against.

PLACEHOLDER until the Research agent is built. Keep the signature and return type; see the
README's "② Research" section for the decisions and tools it should implement.
"""

from classpartai.contracts import Contribution, Research

IS_PLACEHOLDER = True


def research(contribution: Contribution, topic: str) -> Research:
    return Research(route="none", evidence=[], verified=False)
