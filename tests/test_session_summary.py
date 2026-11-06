from types import SimpleNamespace

from classpartai.summary.agent import analyse_session


def test_session_summary():

    # Simulate the same structure as your reviewed transcript.
    def turn(turn_id, speaker_type, student_id, text, start_ms):
        speaker = SimpleNamespace(
            kind=speaker_type,
            studentId=student_id,
        )
        return SimpleNamespace(
            id=turn_id,
            speaker=speaker,
            text=text,
            startMs=start_ms,
        )

    transcript = SimpleNamespace(
        turns=[
            turn(
                "t1",
                "professor",
                None,
                "What is the difference between traditional RAG and Agentic RAG?",
                0,
            ),
            turn(
                "t2",
                "student",
                "Tina",
                "Traditional RAG follows a predefined workflow.",
                5000,
            ),
            turn(
                "t3",
                "student",
                "John",
                "Agentic RAG can decide whether to retrieve again.",
                12000,
            ),
            turn(
                "t4",
                "student",
                "Sarah",
                "Repeated retrieval may increase latency.",
                20000,
            ),
            turn(
                "t5",
                "student",
                "John",
                "Any system using tools is automatically agentic.",
                30000,
            ),
        ]
    )

    # Fake LLM: returns a predictable response.
    def mock_generate_json(system_prompt, user_prompt):
        assert "Session Summary Agent" in system_prompt
        assert "Agentic RAG" in user_prompt

        return {
            "main_topics": [
                {
                    "topic": "Agentic RAG vs Traditional RAG",
                    "explanation": "Students discussed retrieval autonomy.",
                    "turn_ids": ["t1", "t2", "t3"],
                }
            ],
            "agreements": [],
            "disagreements": [],
            "unresolved_questions": [],
            "investigations_needed": [
                {
                    "turn_id": "t5",
                    "claim": "Any system using tools is automatically agentic.",
                    "reason": "Requires verification.",
                }
            ],
            "suggested_followups": [
                "Compare a fixed RAG pipeline with agent-controlled retrieval."
            ],
        }

    result = analyse_session(
        transcript=transcript,
        generate_json=mock_generate_json,
        existing_research={},
    )

    assert result["analysis"]["main_topics"][0]["topic"] == ("Agentic RAG vs Traditional RAG")
    assert result["participation"] == {
        "Tina": 1,
        "John": 2,
        "Sarah": 1,
    }
    assert result["analysis"]["investigations_needed"][0]["turn_id"] == "t5"

    print("\nSESSION SUMMARY TEST PASSED")
    print(result)
