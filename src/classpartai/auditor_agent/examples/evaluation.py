"""One-factor-at-a-time fictional evaluation. Offline doubles are NOT live agent evidence."""

from __future__ import annotations

import argparse
import json
from copy import deepcopy
from dataclasses import asdict

from ..agent import audit_proposal, configured_model
from ..contracts import ContractError
from ..harness import AuditTuning, Limits, ToolCall
from .demo import FakeJudge, FictionalModelDouble, fictional_reader, fictional_request

VARIANTS = {
    "original": AuditTuning(False, False, False),
    "description_only": AuditTuning(True, False, False),
    "description_and_recovery": AuditTuning(True, True, False),
    "all_three": AuditTuning(True, True, True),
}


def cases() -> list[dict]:
    """Authored expectations, not independently human-validated grades or observations."""
    rubric = (
        "Level 0: no relevant concept. Level 1: names observation or interpretation. "
        "Level 2: explains the distinction accurately. Level 3: applies the distinction "
        "to a concrete example with justification. Evaluate the reviewed turn, not source wording."
    )
    defensible = fictional_request("evaluation-defensible")
    defensible["rubric"]["criteria"][0]["description"] = rubric
    overstated = deepcopy(defensible)
    overstated["audit_case_id"] = overstated["state"]["audit_case_id"] = "evaluation-overstated"
    overstated["contributions"][0]["text"] = "Observation and interpretation."
    overstated["proposal"]["findings"][0].update(
        score=3,
        rationale=(
            "The student names observation and interpretation, terms defined by the course handout."
        ),
    )
    inconsistent = deepcopy(defensible)
    inconsistent["audit_case_id"] = inconsistent["state"]["audit_case_id"] = (
        "evaluation-inconsistent"
    )
    peer = deepcopy(inconsistent["contributions"][0])
    peer.update(
        contribution_id="contribution-b", turn_ids=["turn-b"], student_id="fictional-student-b"
    )
    inconsistent["contributions"].append(peer)
    peer_finding = deepcopy(inconsistent["proposal"]["findings"][0])
    inconsistent["proposal"]["findings"][0]["score"] = 1
    peer_finding.update(
        finding_id="finding-b",
        contribution_id="contribution-b",
        transcript_turn_ids=["turn-b"],
        score=3,
    )
    inconsistent["proposal"]["findings"].append(peer_finding)
    flawed = fictional_request("evaluation-unresolved", flawed=True)
    # This pending handoff is a fictional input fixture, not an evaluated/live first Judge run.
    first = audit_proposal(flawed, model=FictionalModelDouble(), evidence_reader=fictional_reader())
    unresolved = FakeJudge.revise(flawed, first.to_dict(), corrected=False)
    return [
        {"name": "defensible", "request": defensible, "expected_verdict": "audit_passed"},
        {
            "name": "overstated_score",
            "request": overstated,
            "expected_verdict": "rejudge_requested",
        },
        {
            "name": "inconsistent_scores",
            "request": inconsistent,
            "expected_verdict": "rejudge_requested",
        },
        {
            "name": "unresolved_revision",
            "request": unresolved,
            "expected_verdict": "professor_review_required",
        },
        {
            "name": "early_finish",
            "request": deepcopy(defensible),
            "expected_verdict": "audit_passed",
        },
    ]


class EvaluationDouble:
    """Same result-dependent scripted policy for all variants; does not inspect descriptions.

    This can prove harness recovery changed, never that prompt wording improved an LLM.
    Live evaluation uses the provider directly and never forces an early finish/comparison.
    """

    def __init__(self, *, early_finish: bool = False):
        self.counter = 0
        self.early_finish = early_finish

    def choose(self, messages: list[dict], tools: list[dict], *, timeout: float) -> ToolCall:
        self.counter += 1
        if tools[0]["function"]["name"] == "citation_assessment":
            data = json.loads(messages[-1]["content"])["untrusted_data"]
            contradictory = "silence proves" in data["rationale"].lower()
            return ToolCall(
                f"eval-{self.counter}",
                "citation_assessment",
                {
                    "relationship": "contradicts" if contradictory else "supports",
                    "quote": data["reference"]["quote"],
                    "explanation": (
                        "Fictional support-review double; does not decide "
                        "whether the score matches rubric level"
                    ),
                },
            )
        if self.early_finish:
            self.early_finish = False
            return self.call(
                "complete_audit",
                {"verdict": "audit_passed", "issues": [], "resolved_issue_ids": []},
            )
        initial = json.loads(messages[1]["content"])["untrusted_data"]
        calls = {}
        observations = []
        for message in messages:
            for call in message.get("tool_calls", []):
                calls[call["id"]] = (
                    call["function"]["name"],
                    json.loads(call["function"]["arguments"]),
                )
            if message["role"] == "tool":
                name, args = calls[message["tool_call_id"]]
                observations.append(
                    (name, args, json.loads(message["content"])["untrusted_tool_result"])
                )
        findings = [
            f
            for name, _, result in observations
            if name == "get_session_scores"
            for f in result.get("findings", [])
        ]
        if not findings:
            return self.call("get_session_scores", {"offset": 0, "limit": 10})
        different = len({f["score"] for f in findings}) > 1
        compared = any(
            name == "compare_similar" and "matches" in result for name, _, result in observations
        )
        if different and not compared:
            return self.call("compare_similar", {"finding_id": findings[0]["finding_id"], "k": 3})
        verified = {
            (args["finding_id"], args["evidence_id"]): result
            for name, args, result in observations
            if name == "verify_citation" and "reference_valid" in result
        }
        for finding in findings:
            for ref in finding["evidence"]:
                pair = (finding["finding_id"], ref["evidence_id"])
                if pair not in verified:
                    return self.call(
                        "verify_citation", {"finding_id": pair[0], "evidence_id": pair[1]}
                    )
        unsupported = next(
            (
                (pair, result)
                for pair, result in verified.items()
                if result["relationship"] != "supports"
            ),
            None,
        )
        naming_only = initial["contributions"][0]["text"] == "Observation and interpretation."
        if unsupported or different or naming_only:
            kind = "citation" if unsupported else "consistency" if different else "rationale"
            objection = (
                "The cited passage contradicts the rationale; revise that evidential claim."
                if unsupported
                else (
                    "Comparable reviewed contributions have different "
                    "levels with no contextual justification; investigate "
                    "the discrepancy against the exact descriptors, not "
                    "wording alone."
                )
                if different
                else (
                    "Level 3 requires application to a concrete example; "
                    "the reviewed turn only names concepts. A supporting "
                    "definition does not demonstrate application."
                )
            )
            return self.call(
                "request_rejudge",
                {
                    "issues": [
                        {
                            "issue_id": "evaluation-objection",
                            "kind": kind,
                            "severity": "material",
                            "finding_ids": [f["finding_id"] for f in findings],
                            "evidence_ids": sorted(
                                {ref["evidence_id"] for f in findings for ref in f["evidence"]}
                            ),
                            "objection": objection,
                        }
                    ]
                },
            )
        pending = initial["pending_objections"]
        return self.call(
            "complete_audit",
            {
                "verdict": "audit_passed",
                "issues": [],
                "resolved_issue_ids": [i["issue_id"] for i in pending["objections"]]
                if pending
                else [],
            },
        )

    def call(self, name: str, arguments: dict) -> ToolCall:
        return ToolCall(f"eval-{self.counter}", name, arguments)


def evaluate(*, live: bool = False) -> dict:
    limits = Limits()
    provider = None
    if live:
        try:
            provider = configured_model()
        except (ContractError, OSError):
            pass
        if provider is None:
            return {
                "execution": "live_blocked",
                "reason": (
                    "Selected provider key or SDK unavailable; no live model evaluation performed"
                ),
                "runs": [],
            }
    report = {
        "execution": "live_model" if live else "fictional_test_double_not_live_evidence",
        "budget": asdict(limits),
        "model": getattr(provider, "model", "EvaluationDouble"),
        "expectation_source": "fictional_authored_not_independently_human_validated",
        "runs": [],
    }
    fixtures = cases()
    for variant, tuning in VARIANTS.items():
        for case in fixtures:
            model = (
                provider if live else EvaluationDouble(early_finish=case["name"] == "early_finish")
            )
            result = audit_proposal(
                deepcopy(case["request"]),
                model=model,
                evidence_reader=fictional_reader(),
                limits=limits,
                tuning=tuning,
            )
            actions = [e for e in result.trace if e["kind"] == "tool"]
            comparisons = sum(e["tool"] == "compare_similar" for e in actions)
            report["runs"].append(
                {
                    "variant": variant,
                    "case": case["name"],
                    "expected_verdict": case["expected_verdict"],
                    "verdict": result.verdict,
                    "matches_authored_expectation": result.verdict == case["expected_verdict"],
                    "stop_reason": result.stop_reason,
                    "usage": result.usage,
                    "tool_route": [e["tool"] for e in actions],
                    "invalid_calls": sum(e["outcome"] == "invalid" for e in actions),
                    "pass_blocked_observations": sum(
                        e["outcome"] == "pass_blocked" for e in actions
                    ),
                    "comparison_calls": comparisons,
                    "comparison_case_expected": case["name"] == "inconsistent_scores",
                    "comparison_support_requires_professor_check": live,
                    "useful_comparisons_fixture_proxy": comparisons
                    if case["name"] == "inconsistent_scores"
                    else 0,
                    "unnecessary_comparisons_fixture_proxy": comparisons
                    if case["name"] != "inconsistent_scores"
                    else 0,
                    "issues": [asdict(i) for i in result.issues],
                }
            )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Controlled Auditor experiment; --live explicitly invokes the selected hosted provider"
        )
    )
    parser.add_argument(
        "--live", action="store_true", help="Live API calls if configured; otherwise report blocked"
    )
    args = parser.parse_args()
    print(json.dumps(evaluate(live=args.live), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
