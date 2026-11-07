"""How it works: the course-terms map, the brief and the reflection render."""

from classpartai import course_map


def test_every_part_of_the_system_is_mapped_to_a_course_topic():
    parts = {row[0] for row in course_map.TOPIC_ROWS}
    assert {"Listener", "Coordinator", "Research", "Judge", "Auditor"} <= parts
    assert all("(S" in row[2] for row in course_map.TOPIC_ROWS)  # every term cites a slide


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
    assert len(at.subheader) == 4
