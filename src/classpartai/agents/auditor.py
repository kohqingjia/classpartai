"""④ Auditor: challenge the Judge's scores before anything is acted on.

PLACEHOLDER until the Auditor agent is built: approves every judgement unchanged.
Keep the signature and return type.
"""

from classpartai.contracts import Audit, Contribution, Judgement

IS_PLACEHOLDER = True


def audit(contribution: Contribution, judgement: Judgement) -> Audit:
    return Audit(verdict="approved", issues=[])
