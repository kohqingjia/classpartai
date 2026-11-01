from classpartai.agents import listener
from classpartai.orchestrator import score_session


def test_listener_output_maps_onto_contributions():
    result = {
        "segments": [
            {
                "start": 0.0,
                "end": 5.0,
                "speaker": "Alex Tan",
                "text": "Agentic RAG rewrites the query first.",
            },
            {"start": 5.0, "end": 6.0, "speaker": "UNKNOWN", "text": "Pardon?"},
            {
                "start": 6.0,
                "end": 9.0,
                "speaker": "AMBIGUOUS",
                "text": "I agree with that point entirely.",
            },
        ]
    }
    contributions = listener.to_contributions(result, "s1", {"Alex Tan": "alex-tan"})
    assert [c.person_id for c in contributions] == ["alex-tan", None, None]
    assert [c.speaker_status for c in contributions] == ["identified", "unknown", "ambiguous"]
    assert [c.substantive for c in contributions] == [True, False, True]


def test_only_identified_substantive_contributions_are_scored():
    result = {
        "segments": [
            {
                "start": 0.0,
                "end": 5.0,
                "speaker": "Alex Tan",
                "text": "Agentic RAG rewrites the query first.",
            },
            {
                "start": 5.0,
                "end": 9.0,
                "speaker": "UNKNOWN",
                "text": "Could it retrieve forever if nothing matches?",
            },
        ]
    }
    contributions = listener.to_contributions(result, "s1", {"Alex Tan": "alex-tan"})
    session = score_session(contributions, "s1", "IS469", "2026-11-01")
    assert session.items[0].judgement is not None and session.items[0].audit is not None
    assert session.items[1].judgement is None
    assert session.placeholder_stages == ["research", "judge", "auditor"]
