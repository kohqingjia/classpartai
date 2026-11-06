import altair as alt
import pandas as pd
import streamlit as st


def render_session_summary(result):
    analysis = result.get("analysis", {})
    participation = result.get("participation", {})

    topics = analysis.get("main_topics") or []
    agreements = analysis.get("agreements") or []
    disagreements = analysis.get("disagreements") or []
    questions = analysis.get("unresolved_questions") or []
    investigations = analysis.get("investigations_needed") or []
    followups = analysis.get("suggested_followups") or []

    st.title("Session Summary")
    st.caption("Key discussions, learning gaps, and recommended follow-ups.")

    # Overview metrics
    col1, col2, col3 = st.columns(3)

    col1.metric("Discussion Topics", len(topics))
    col2.metric("Disagreements", len(disagreements))
    col3.metric("Open Questions", len(questions))

    st.divider()

    # Main discussion topics
    st.subheader("Main Discussion Topics")

    if topics:
        cols = st.columns(2)

        for i, topic in enumerate(topics):
            with cols[i % 2]:
                with st.container(border=True):
                    st.markdown(f"**{topic.get('topic', 'Untitled topic')}**")
                    st.caption(topic.get("explanation", ""))
    else:
        st.info("No major discussion topics identified.")

    # Agreement and disagreement
    st.subheader("Discussion Dynamics")

    left, right = st.columns(2)

    with left:
        with st.container(border=True):
            st.markdown("**Areas of Agreement**")

            if agreements:
                for item in agreements:
                    st.write(item.get("description", ""))
            else:
                st.caption("No clear agreements identified.")

    with right:
        with st.container(border=True):
            st.markdown("**Areas of Disagreement**")

            if disagreements:
                for item in disagreements:
                    st.write(item.get("description", ""))
            else:
                st.caption("No clear disagreements identified.")

    # Unresolved questions
    st.subheader("Needs Attention")

    with st.expander(
        f"Unresolved Questions ({len(questions)})",
        expanded=False,
    ):
        if questions:
            for item in questions:
                st.write(item.get("question", ""))
        else:
            st.caption("No unresolved questions identified.")

    # Claims awaiting research
    with st.expander(
        f"Factual Claims to Verify ({len(investigations)})",
        expanded=False,
    ):
        if investigations:
            for item in investigations:
                st.markdown(f"**{item.get('claim', '')}**")
                st.caption(item.get("reason", ""))
        else:
            st.caption("No claims flagged for verification.")

    # Participation overview
    st.subheader("Participation Overview")

    if participation:
        chart_data = pd.DataFrame(
            [
                {
                    "Student": name,
                    "Speaking turns": count,
                }
                for name, count in participation.items()
            ]
        )

        chart_data = chart_data.sort_values(
            "Speaking turns",
            ascending=False,
        )

        # Allocate enough vertical space for each student.
        chart_height = max(180, len(chart_data) * 65)

        chart = (
            alt.Chart(chart_data)
            .mark_bar(
                size=18,
                cornerRadiusEnd=4,
            )
            .encode(
                y=alt.Y(
                    "Student:N",
                    sort=alt.SortField(
                        field="Speaking turns",
                        order="descending",
                    ),
                    title=None,
                    axis=alt.Axis(
                        labelAngle=0,
                        labelPadding=12,
                        labelLimit=160,
                        ticks=False,
                        domain=False,
                    ),
                    scale=alt.Scale(
                        paddingInner=0.55,
                        paddingOuter=0.25,
                    ),
                ),
                x=alt.X(
                    "Speaking turns:Q",
                    title="Number of speaking turns",
                    axis=alt.Axis(
                        tickMinStep=1,
                        format="d",
                    ),
                    scale=alt.Scale(
                        domainMin=0,
                        nice=True,
                    ),
                ),
                tooltip=[
                    alt.Tooltip("Student:N"),
                    alt.Tooltip(
                        "Speaking turns:Q",
                        format="d",
                    ),
                ],
            )
            .properties(height=chart_height)
        )

        st.altair_chart(
            chart,
            use_container_width=True,
        )

        st.caption("Counts reflect speaking turns, not CP scores.")
    else:
        st.info("No student participation data available.")

    # Follow-up actions
    st.subheader("Suggested Professor Follow-ups")

    if followups:
        for i, item in enumerate(followups, start=1):
            with st.container(border=True):
                st.markdown(f"**{i}.** {item}")
    else:
        st.caption("No follow-up actions suggested.")
