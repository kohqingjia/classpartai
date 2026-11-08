"""How it works: the agentic controls section."""

from classpartai import course_map


def test_all_six_controls_for_agents_are_covered():
    assert [c for c, _ in course_map.SIX_CONTROLS] == [
        "Allow-list",
        "Own identity",
        "Approval",
        "Full log",
        "Limits and stop",
        "Distrust inputs",
    ]


def test_the_sections_render():
    from streamlit.testing.v1 import AppTest

    def page():
        from classpartai import course_map

        course_map.render()

    at = AppTest.from_function(page).run()
    assert not at.exception
    assert len(at.subheader) == 1
