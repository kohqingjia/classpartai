from classpartai.research.agent import EvidencePack, correctness
from classpartai.research.evaluate import compare, format_table, load_labelled, score

from .conftest import SAMPLE


def pack(route="course", statuses=("supported",), docs=("readings/a.md",), quote="q", answers=None):
    evidence = [
        {"source_type": "reading", "doc": d, "quote": quote, "id": f"C{i}"}
        for i, d in enumerate(docs)
    ]
    claims = [{"claim": f"c{i}", "status": s, "evidence": evidence} for i, s in enumerate(statuses)]
    return EvidencePack(
        text="t",
        date="2026-09-01",
        kind="contribution",
        contribution_id=None,
        lesson=None,
        route=route,
        route_reason="",
        on_topic=True,
        on_topic_reason="",
        question="q?",
        claims=claims,
        correctness=correctness(claims),
        reasoning=None,
        mistake=None,
        answers_question=answers,
        expected_points=[],
        missed_points=[],
        summary="",
        needs_review=False,
        stop_reason="submitted",
        usage={"llm_calls": 3, "course_searches": 1, "web_searches": 0, "seconds": 1.0},
    )


def test_correctness_from_claim_verdicts():
    assert pack(statuses=("supported", "contradicted")).correctness == "partially_correct"
    assert pack(statuses=("contradicted", "unverified")).correctness == "incorrect"
    assert pack(statuses=("unverified", "supported")).correctness == "correct"
    assert pack(statuses=("partially_supported",)).correctness == "unverified"
    assert pack(statuses=()).correctness is None


def test_answers_question_is_scored_separately_from_correctness():
    item = {
        "id": "x",
        "expected_sources": ["course"],
        "expected_correctness": "correct",
        "expected_answers_question": "no",
        "gold_docs": [],
    }
    row = score(item, pack(answers="no"))
    assert row["correctness_ok"] and row["answers_question_ok"]
    assert score(item, pack(answers="yes"))["answers_question_ok"] is False


def test_routing_rules():
    item = {
        "id": "x",
        "expected_sources": ["course"],
        "expected_correctness": "correct",
        "gold_docs": [],
    }
    assert score(item, pack(route="course"))["routed_correctly"]
    assert not score(item, pack(route="course+web"))["routed_correctly"]  # web was not needed
    none = {"id": "y", "expected_sources": ["none"], "expected_correctness": None, "gold_docs": []}
    assert score(none, pack(route="none", statuses=()))["routed_correctly"]
    assert not score(none, pack(route="course"))["routed_correctly"]


def test_status_and_context_precision():
    item = {
        "id": "x",
        "expected_sources": ["course"],
        "expected_correctness": "correct",
        "gold_docs": ["readings/a.md"],
    }
    row = score(item, pack(docs=("readings/a.md", "slides/b.md")))
    assert row["correctness_ok"] and row["context_precision"] == 0.5 and row["gold_hit"]
    row = score(item, pack(statuses=("unverified",), docs=()))
    assert row["context_precision"] == 0.0 and row["gold_hit"] is False


def test_compare_reports_both_systems():
    items = [
        {
            "id": "x",
            "expected_sources": ["course"],
            "expected_correctness": "correct",
            "gold_docs": [],
        }
    ]
    report = compare(items, lambda i: pack(), lambda i: pack())
    assert report["single_pass"]["summary"]["routed_correctly"] is None
    assert report["agentic"]["summary"]["correctness_ok"] == 1.0
    assert "| correctness_ok | 1.00 | 1.00 |" in format_table(report)


def test_labelled_set_is_well_formed():
    items = load_labelled(SAMPLE / "eval_contributions.jsonl")
    assert len(items) >= 12 and len({i["id"] for i in items}) == len(items)
    for item in items:
        assert set(item["expected_sources"]) <= {"none", "course", "web"}
        for doc in item["gold_docs"]:
            assert (SAMPLE / doc).is_file(), doc


def test_reasoning_and_mistake_metrics():
    item = {
        "id": "x",
        "expected_sources": ["course"],
        "expected_correctness": "incorrect",
        "expected_reasoning": "explained",
        "expected_mistake": "reasonable_guess",
        "gold_docs": [],
    }
    wrong = pack(statuses=("contradicted",))
    wrong.reasoning, wrong.mistake = "explained", {"type": "reasonable_guess", "reason": ""}
    row = score(item, wrong)
    assert row["reasoning_ok"] and row["mistake_ok"]
    wrong.mistake = None
    assert score(item, wrong)["mistake_ok"] is False
    # a null label means "no mistake should be reported"; no label means "not scored"
    assert score({**item, "expected_mistake": None}, wrong)["mistake_ok"] is True
    assert (
        score({k: v for k, v in item.items() if k != "expected_mistake"}, wrong)["mistake_ok"]
        is None
    )
