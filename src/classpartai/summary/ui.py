
import streamlit as st


def render_session_summary(result):
    """Display the Session Summary Agent's results."""

    analysis = result["analysis"]
    participation = result["participation"]

    st.subheader("Session Summary")
    st.caption("AI-generated professor briefing")

    st.markdown("### Main Discussion Topics")

    for topic in analysis.get("main_topics", []):
        st.markdown(f"**{topic['topic']}**")
        st.write(topic["explanation"])

    st.markdown("### Areas of Agreement")

    agreements = analysis.get("agreements", [])
    if agreements:
        for item in agreements:
            st.write(item["description"])
    else:
        st.info("No clear agreements identified.")

    st.markdown("### Areas of Disagreement")

    disagreements = analysis.get("disagreements", [])
    if disagreements:
        for item in disagreements:
            st.write(item["description"])
    else:
        st.info("No clear disagreements identified.")

    st.markdown("### Unresolved Questions")

    questions = analysis.get("unresolved_questions", [])
    if questions:
        for item in questions:
            st.write(item["question"])
    else:
        st.info("No unresolved questions identified.")

    st.markdown("### Claims Requiring Investigation")

    investigations = analysis.get("investigations_needed", [])
    if investigations:
        for item in investigations:
            st.warning(
                f"{item['claim']}\n\n"
                f"Reason: {item['reason']}"
            )
    else:
        st.success("No additional investigation requested.")

    st.markdown("### Participation Overview")

    if participation:
        st.bar_chart(participation)
        st.caption("Counts reflect speaking turns, not CP scores.")
    else:
        st.info("No identified student turns.")

    st.markdown("### Suggested Professor Follow-ups")

    for suggestion in analysis.get("suggested_followups", []):
        st.write(f"• {suggestion}")
