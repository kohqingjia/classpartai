"""Two audit failures from the Demo 2-7 runs after #65."""

from conftest import full_proposal

from classpartai.participation.schema import ModelAudit, Proposal
from classpartai.participation.validation import compose_draft


def audit(issues=(), resolved=()):
    return ModelAudit(
        issues=list(issues),
        resolvedIssueIds=list(resolved),
        resolutionReason="Checked the turn again.",
        notes="Audit notes.",
    )


RAISED = {
    "id": "thin",
    "studentId": "alex-tan",
    "criterionId": None,
    "detail": "Thin.",
    "kind": "support",
}


def test_resolving_an_issue_that_isnt_open_is_ignored_not_refused(inputs):
    """Demo 2 (run fdb3c4d4): one bad ID refused the whole audit, again and again."""
    proposal = Proposal.model_validate(full_proposal())
    first = compose_draft(proposal, inputs, "first", None, audit([RAISED]))
    assert "model:thin" in {i.id for i in first.audit.issues}
    second = compose_draft(
        proposal, inputs, "second", first, audit(resolved=["thin", "model:never-raised"])
    )
    thin = next(i for i in second.audit.issues if i.id == "model:thin")
    assert thin.disposition == "revised"  # the missing "model:" prefix is forgiven
    assert "model:never-raised" not in {i.id for i in second.audit.issues}


def test_the_fallback_audit_leaves_out_the_course_documents(inputs, monkeypatch):
    """Demo 3 (run 81c4f024): the documents alone broke the 100 KB history limit."""
    from classpartai.participation import roles

    seen = {}
    monkeypatch.setattr(roles, "role_result", lambda *a, **k: seen.setdefault("data", a[3]))
    draft = compose_draft(Proposal.model_validate(full_proposal()), inputs, "d")
    roles.model_audit.__wrapped__(inputs, draft, [], None, None)
    assert "documents" not in seen["data"]["inputs"]
