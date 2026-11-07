"""ClassPart AI Auditor; the workflow runs it via participation/auditor_bridge.py."""

from .agent import AuditorAgent, audit_proposal
from .contracts import AuditRequest, AuditResult, ContractError
from .harness import Limits, Model, ToolCall
from .tools import Evidence, EvidenceReader

__all__ = [
    "AuditorAgent",
    "AuditRequest",
    "AuditResult",
    "ContractError",
    "Evidence",
    "EvidenceReader",
    "Limits",
    "Model",
    "ToolCall",
    "audit_proposal",
]
