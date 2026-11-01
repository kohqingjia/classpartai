import pytest
from conftest import SILENT, feedback, finding, full_proposal

from classpartai.participation.schema import Proposal
from classpartai.participation.validation import (
    Unprocessable,
    audit_draft,
    totals,
    validate_proposal,
)


def check(inputs, raw):
    validate_proposal(Proposal.model_validate(raw), inputs, [], "s1")


def with_finding(f):
    raw = full_proposal()
    raw["findings"][0] = f
    return raw


def test_complete_proposal_is_valid(inputs):
    check(inputs, full_proposal())


@pytest.mark.parametrize(
    ("bad", "message"),
    [
        (finding("alex-tan", "reasoning", 9, ["turn-002"]), "outside the pinned rubric range"),
        (
            finding("alex-tan", "reasoning", 0, [], "insufficient_evidence"),
            "not be counted as zero",
        ),
        (finding("alex-tan", "reasoning", 2, []), "attributable transcript evidence"),
        (finding("alex-tan", "reasoning", 2, ["turn-003"]), "another student"),
        (finding("alex-tan", "reasoning", 2, ["turn-007"]), "Uncertain or professor turns"),
        (finding("marcus-lee", "reasoning", 0, []), "No observed contribution"),
        (finding("ghost", "reasoning", 1, ["turn-002"]), "Unknown roster student"),
    ],
)
def test_finding_rules(inputs, bad, message):
    with pytest.raises(Unprocessable, match=message):
        check(inputs, with_finding(bad))


def test_feedback_may_not_name_another_student(inputs):
    raw = full_proposal()
    raw["feedback"][0] = feedback("alex-tan", "Clearer than Priya Nair's question.")
    with pytest.raises(Unprocessable, match="another roster student"):
        check(inputs, raw)


def test_silent_student_feedback_must_say_so(inputs):
    raw = full_proposal()
    raw["feedback"][3] = feedback("marcus-lee", "Great work today.")
    with pytest.raises(Unprocessable, match="no observed contribution"):
        check(inputs, raw)


def test_audit_blocks_missing_coverage_and_flags_uncertainty(inputs):
    raw = full_proposal()
    raw["feedback"] = raw["feedback"][:3]
    issues = {i.id: i.severity for i in audit_draft(Proposal.model_validate(raw), inputs)}
    assert issues["feedback:marcus-lee"] == "blocking"
    assert issues["no-observation:marcus-lee"] == "review"
    assert issues["attribution:uncertain"] == "review"


def test_audit_flags_trait_claims(inputs):
    raw = full_proposal()
    raw["feedback"][1] = feedback("priya-nair", "Shows poor understanding of RAG.")
    ids = [i.id for i in audit_draft(Proposal.model_validate(raw), inputs)]
    assert "unsupported-trait:priya-nair" in ids


def test_totals_only_when_every_criterion_is_scored(inputs):
    proposal = Proposal.model_validate(full_proposal())
    assert totals(proposal, inputs, "alex-tan")["total"] == 6
    marcus = totals(proposal, inputs, "marcus-lee")
    assert marcus["total"] is None and "unknown scores are not zero" in marcus["limitation"]
    assert SILENT.startswith("No observed contribution")
