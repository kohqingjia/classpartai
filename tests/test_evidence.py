from conftest import ScriptedDriver

from classpartai.evidence import CourseIndex, Investigation, SearchArgs, investigate

EXCERPT = "Each extra retrieval round adds a model call"


def request(session_id="s1"):
    return Investigation(
        sessionId=session_id,
        question="Is the latency trade-off Alex describes supported by the notes?",
        turnIds=["turn-005"],
        criterionIds=["reasoning"],
    )


def search(query, limit=3):
    return (
        "search_course_passages",
        {"query": query, "documentId": None, "version": None, "limit": limit},
    )


def finish(status="sufficient", passage="w10-agentic-rag:1:p3", excerpt=EXCERPT, gaps=()):
    return (
        "finish_evidence",
        {
            "status": status,
            "explanation": "The notes state the latency cost directly.",
            "turnIds": ["turn-005"],
            "citations": [
                {
                    "passageId": passage,
                    "excerpt": excerpt,
                    "relevance": "Matches the claim",
                    "relationship": "supports",
                }
            ]
            if status == "sufficient"
            else [],
            "conflicts": [],
            "gaps": list(gaps),
        },
    )


def test_lexical_search_stems_and_ranks(inputs):
    index = CourseIndex(inputs)
    hits = index.search(
        SearchArgs(query="retrieval latency", documentId=None, version=None, limit=3)
    )
    assert hits[0].passageId == "w10-agentic-rag:1:p3"
    assert index.search(SearchArgs(query="zebra", documentId=None, version=None, limit=3)) == []


def test_query_syntax_is_made_safe():
    assert CourseIndex.to_match('rewrite OR "multi hop" -noise NEAR(') == (
        '"rewrite" OR "multi hop" "noise" "NEAR"'
    )


def test_agent_reformulates_then_finishes_with_cited_evidence(inputs):
    driver = ScriptedDriver([search("speed penalty"), search("retrieval latency"), finish()])
    outcome = investigate(request(), inputs, driver, CourseIndex(inputs))
    assert outcome.status == "completed"
    assert [a["tool"] for a in outcome.progress.actions] == [
        "search_course_passages",
        "search_course_passages",
        "finish_evidence",
    ]
    assert outcome.progress.bundle.citations[0].title == "Week 10 notes: Agentic RAG"


def test_citation_must_be_an_exact_retrieved_excerpt(inputs):
    driver = ScriptedDriver(
        [
            search("retrieval latency"),
            finish(excerpt="Agentic RAG is always slower"),  # not in the passage: refused
            finish("gap", gaps=["Notes don't quantify the latency"]),
        ]
    )
    outcome = investigate(request(), inputs, driver, CourseIndex(inputs))
    actions = outcome.progress.actions
    assert actions[1]["outcome"] == "invalid" and "exact returned excerpt" in actions[1]["summary"]
    assert outcome.status == "needs_review" and outcome.stopReason == "model_reported_gap"


def test_cannot_cite_a_passage_it_never_retrieved(inputs):
    driver = ScriptedDriver([finish()] + [search("x")] * 7)
    outcome = investigate(request(), inputs, driver, CourseIndex(inputs))
    assert outcome.progress.actions[0]["outcome"] == "invalid"
    assert outcome.stopReason == "model_or_tool_budget"
    assert outcome.progress.bundle.status == "gap"


def test_unknown_tool_is_refused_not_run(inputs):
    driver = ScriptedDriver([("send_email", {"to": "x"}), finish("gap", gaps=["none found"])])
    outcome = investigate(request(), inputs, driver, CourseIndex(inputs))
    assert outcome.progress.actions[0]["tool"] == "unsupported_tool"
    assert outcome.progress.actions[0]["outcome"] == "invalid"


def test_empty_filter_is_invalid_not_an_empty_search(inputs):
    driver = ScriptedDriver(
        [
            (
                "search_course_passages",
                {"query": "latency", "documentId": "", "version": None, "limit": 3},
            ),
            finish("gap", gaps=["n/a"]),
        ]
    )
    outcome = investigate(request(), inputs, driver, CourseIndex(inputs))
    summary = outcome.progress.actions[0]["summary"]
    assert summary.startswith("Invalid search arguments (documentId")
    assert "latency" not in summary  # the reason names the field, never echoes input


def test_natural_language_query_ignores_stopwords(inputs):
    index = CourseIndex(inputs)
    query = "Is there a cost to the extra retrieval rounds in agentic RAG?"
    hits = index.search(SearchArgs(query=query, documentId=None, version=None, limit=3))
    assert hits and hits[0].passageId == "w10-agentic-rag:1:p3"
