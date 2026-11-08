"""The TA cost comparison: arithmetic on a measured run, and the Evaluation page renders."""

import pytest

from classpartai.costing import Assumptions, estimate

MEASURED = {
    "run": {"usd": 0.10, "contributions": 5, "seconds": 300},
    "listener": {"pipeline_seconds": 830.0, "audio_seconds": 500.0},
}


def test_the_semester_cost_scales_the_measured_run_by_contributions():
    a = Assumptions(contributions=20, lessons=12, server_sgd_month=32.5, semester_months=4)
    e = estimate(MEASURED, a)
    # US$0.02 a contribution × 20 × 1.30 = S$0.52 a lesson; the server is S$32.50 × 4
    assert e["model_per_lesson"] == pytest.approx(0.52)
    assert e["server_semester"] == pytest.approx(130.0)
    assert e["software_semester"] == pytest.approx(130.0 + 0.52 * 12)
    assert e["saving_semester"] == pytest.approx(590 - e["software_semester"])
    assert e["ta_per_class_hour"] == pytest.approx(590 / 36)
    assert e["listener_hours_per_lesson"] == pytest.approx(830 / 500 * 3)
    assert e["assessment_minutes_per_lesson"] == pytest.approx(60 / 60 * 20)
    assert e["review_minutes_per_lesson"] == 20
    assert e["break_even_model_per_lesson"] == pytest.approx((590 - 130) / 12)


def test_the_evaluation_page_renders(monkeypatch):
    from streamlit.testing.v1 import AppTest

    from classpartai import costing

    monkeypatch.setattr(
        costing,
        "measured",
        lambda path=None, records=None: {
            "source": "file",
            "run": {
                **MEASURED["run"],
                "id": "abcd1234",
                "session": "Demo 1",
                "recordedAt": "2026-11-07",
                "model": "gpt-5-mini",
                "stopReason": "ready_for_professor_review",
                "students": 4,
                "audio_seconds": 94,
                "modelCalls": 40,
                "byAgent": {
                    "judge": {
                        "calls": 2,
                        "input_tokens": 10,
                        "cached_tokens": 0,
                        "output_tokens": 5,
                        "usd": 0.01,
                    }
                },
            },
            "listener": {**MEASURED["listener"], "cpu": "4-core"},
            "prices": {"source": "data/model_prices.json", "usdPerMillionTokens": {}},
        },
    )

    def page():
        from classpartai.evaluation_ui import evaluation_view

        evaluation_view()

    at = AppTest.from_function(page, default_timeout=30).run()
    assert not at.exception
    assert any("Teaching assistant" in getattr(h, "value", "") for h in at.get("html"))
    assert any("Research" in s.value for s in at.subheader)
