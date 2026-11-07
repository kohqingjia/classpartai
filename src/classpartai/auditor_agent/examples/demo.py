"""Fictional Judge and model TEST DOUBLES. This demo does not demonstrate live LLM behaviour."""

from __future__ import annotations

import json
from copy import deepcopy

from ..agent import audit_proposal
from ..contracts import Scope
from ..harness import ToolCall
from ..tools import Evidence


def fictional_request(case_id: str = "fictional-case-1", *, flawed: bool = False) -> dict:
    return {
        "schema_version": 1,
        "audit_case_id": case_id,
        "trusted_scope": {"course_id": "fictional-course", "session_id": "fictional-session"},
        "rubric": {
            "rubric_id": "fictional-rubric",
            "version": "1",
            "criteria": [
                {
                    "criterion_id": "reasoning",
                    "description": (
                        "Justify an interpretation with relevant evidence; "
                        "defensible challenges are welcome."
                    ),
                    "minimum": 0,
                    "maximum": 3,
                }
            ],
        },
        "contributions": [
            {
                "contribution_id": "contribution-a",
                "turn_ids": ["turn-a"],
                "student_id": "fictional-student-a",
                "attribution": "identified",
                "text": (
                    "Silence alone does not show poor understanding; another observation is needed."
                ),
                "start_ms": 0,
                "end_ms": 8000,
            }
        ],
        "proposal": {
            "schema_version": 1,
            "reference": {"proposal_id": "fictional-proposal", "version": 1},
            "previous_proposal": None,
            "rejudge_request_id": None,
            "rubric_id": "fictional-rubric",
            "rubric_version": "1",
            "findings": [
                {
                    "finding_id": "finding-a",
                    "contribution_id": "contribution-a",
                    "criterion_id": "reasoning",
                    "score": 2,
                    "rationale": "The passage says silence proves poor understanding."
                    if flawed
                    else (
                        "The contribution distinguishes observation from "
                        "interpretation; the passage says silence alone is "
                        "insufficient."
                    ),
                    "transcript_turn_ids": ["turn-a"],
                    "evidence": [
                        {
                            "evidence_id": "evidence-a",
                            "source_id": "fictional-handout",
                            "source_version": "1",
                            "passage_id": "passage-a",
                            "page": 1,
                            "quote": "Silence alone is insufficient evidence of understanding.",
                        }
                    ],
                }
            ],
        },
        "state": {
            "schema_version": 1,
            "audit_case_id": case_id,
            "scope": {"course_id": "fictional-course", "session_id": "fictional-session"},
            "rubric_id": "fictional-rubric",
            "rubric_version": "1",
            "state_version": 0,
            "rejudge_count": 0,
            "last_proposal": None,
            "pending_rejudge": None,
            "terminal": False,
            "input_fingerprint": None,
            "finding_bindings": {},
        },
    }


class MemoryEvidenceReader:
    """Local demo adapter. A real adapter must enforce authenticated course ownership in queries."""

    def __init__(self, rows: list[Evidence]):
        self.rows = rows

    def read(self, scope: Scope, evidence_id: str, *, timeout: float) -> Evidence | None:
        return next(
            (r for r in self.rows if r.scope == scope and r.evidence_id == evidence_id), None
        )


def fictional_reader() -> MemoryEvidenceReader:
    return MemoryEvidenceReader(
        [
            Evidence(
                Scope("fictional-course", "fictional-session"),
                "evidence-a",
                "fictional-handout",
                "1",
                "passage-a",
                1,
                (
                    "Silence alone is insufficient evidence of "
                    "understanding. An observation records what happened; "
                    "an interpretation requires further evidence."
                ),
            )
        ]
    )


class FakeJudge:
    """Fictional proposal adapter, NOT the team's real Judge. Never computes a new score."""

    @staticmethod
    def revise(request: dict, audit_result: dict, *, corrected: bool) -> dict:
        if audit_result["verdict"] != "rejudge_requested":
            raise ValueError("Fake Judge needs an actual targeted handoff")
        revised = deepcopy(request)
        revised["state"] = deepcopy(audit_result["updated_state"])
        proposal = revised["proposal"]
        proposal["previous_proposal"] = deepcopy(proposal["reference"])
        proposal["reference"]["version"] += 1
        proposal["rejudge_request_id"] = audit_result["rejudge_request"]["request_id"]
        if corrected:
            proposal["findings"][0]["rationale"] = fictional_request()["proposal"]["findings"][0][
                "rationale"
            ]
        return revised


class FictionalModelDouble:
    """Result-dependent deterministic test fixture, explicitly NOT a production agent.

    The real loop delegates choices to the injected model. This fixture merely exercises its
    protocol, including an alternative optional comparison route and nested support review.
    """

    def __init__(self, *, compare_first: bool = False):
        self.counter = 0
        self.compare_first = compare_first

    def choose(self, messages: list[dict], tools: list[dict], *, timeout: float) -> ToolCall:
        self.counter += 1
        if tools[0]["function"]["name"] == "citation_assessment":
            data = json.loads(messages[-1]["content"])["untrusted_data"]
            bad = "silence proves" in data["rationale"].lower()
            return ToolCall(
                f"double-{self.counter}",
                "citation_assessment",
                {
                    "relationship": "contradicts" if bad else "supports",
                    "quote": "Silence alone is insufficient evidence of understanding.",
                    "explanation": (
                        "Fictional semantic-review double: rationale contradicts the passage"
                    )
                    if bad
                    else "Fictional semantic-review double: the distinction matches this passage",
                },
            )
        prior = []
        for m in messages:
            if m["role"] == "tool":
                prior.append(json.loads(m["content"])["untrusted_tool_result"])
        initial = json.loads(messages[1]["content"])["untrusted_data"]
        finding_id = initial["finding_ids"][0]
        if self.compare_first and not any("method" in p for p in prior):
            name, args = "compare_similar", {"finding_id": finding_id, "k": 3}
        elif not any("findings" in p for p in prior):
            name, args = "get_session_scores", {"offset": 0, "limit": 10}
        elif not any("relationship" in p for p in prior):
            name, args = "verify_citation", {"finding_id": finding_id, "evidence_id": "evidence-a"}
        else:
            check = next(p for p in prior if "relationship" in p)
            if check["relationship"] != "supports":
                name, args = (
                    "request_rejudge",
                    {
                        "issues": [
                            {
                                "issue_id": "unsupported-rationale",
                                "kind": "citation",
                                "severity": "material",
                                "finding_ids": [finding_id],
                                "evidence_ids": ["evidence-a"],
                                "objection": (
                                    "The exact source quotation does not "
                                    "support the rationale; revise the "
                                    "rationale against the cited passage, "
                                    "retaining uncertainty."
                                ),
                            }
                        ]
                    },
                )
            else:
                pending = initial["pending_objections"]
                name, args = (
                    "complete_audit",
                    {
                        "verdict": "audit_passed",
                        "issues": [],
                        "resolved_issue_ids": [i["issue_id"] for i in pending["objections"]]
                        if pending
                        else [],
                    },
                )
        return ToolCall(f"double-{self.counter}", name, args)


def run_demo() -> dict:
    defensible = audit_proposal(
        fictional_request("fictional-defensible"),
        model=FictionalModelDouble(compare_first=True),
        evidence_reader=fictional_reader(),
    )
    request = fictional_request("fictional-rejudge", flawed=True)
    first = audit_proposal(
        request, model=FictionalModelDouble(), evidence_reader=fictional_reader()
    )
    corrected = audit_proposal(
        FakeJudge.revise(request, first.to_dict(), corrected=True),
        model=FictionalModelDouble(),
        evidence_reader=fictional_reader(),
    )
    unresolved = audit_proposal(
        FakeJudge.revise(request, first.to_dict(), corrected=False),
        model=FictionalModelDouble(),
        evidence_reader=fictional_reader(),
    )

    # Explicit double chooses an early finish, then observes pass_blocked and recovers.
    class EarlyFinishDouble(FictionalModelDouble):
        early = True

        def choose(self, messages, tools, *, timeout):
            if self.early:
                self.early = False
                return ToolCall(
                    "early-finish",
                    "complete_audit",
                    {"verdict": "audit_passed", "issues": [], "resolved_issue_ids": []},
                )
            return super().choose(messages, tools, timeout=timeout)

    recovered = audit_proposal(
        fictional_request("fictional-recovery"),
        model=EarlyFinishDouble(),
        evidence_reader=fictional_reader(),
    )
    return {
        "early_finish_recovery": recovered.to_dict(),
        "label": "FICTIONAL TEST DOUBLE DEMO — not live model behaviour or actual assessment",
        "defensible": defensible.to_dict(),
        "first_audit": first.to_dict(),
        "corrected_revision": corrected.to_dict(),
        "unresolved_revision": unresolved.to_dict(),
    }


def main() -> None:
    print(json.dumps(run_demo(), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
