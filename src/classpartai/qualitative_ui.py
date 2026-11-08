"""The Evaluation page's qualitative review: read the real outputs and answer the questions.

Two people review the same run separately (the second without seeing the first's answers) and the
comparison below says where they differ. Storage and the questions are in qualitative.py.
"""

from __future__ import annotations

import streamlit as st

from classpartai import qualitative as q


def review_form(stamp: str, run: dict, reviewer: str) -> None:
    sessions = [s for s in run["sessions"] if s.get("outputs")]
    if not sessions:
        st.info("This run produced no drafts to read.", icon=":material/info:")
        return
    saved = q.load(stamp, reviewer).get("reviews", {})
    done, total = q.progress(stamp, reviewer, run)
    st.progress(done / total if total else 0.0, text=f"{done} of {total} outputs fully answered")
    by_id = {s["id"]: s for s in sessions}
    picked = st.selectbox(
        "Session",
        list(by_id),
        format_func=lambda i: f"{i}: {by_id[i]['case']}",
        key=f"qual-session-{reviewer}",
    )
    session = by_id[picked]
    with st.form(f"qual-{stamp}-{reviewer}-{picked}"):
        entered: dict[str, dict] = {}
        for student, out in session["outputs"].items():
            item = saved.get(q.key(picked, student), {})
            with st.container(border=True):
                st.markdown(f"**{student}**")
                st.markdown("\n".join(f"- {f}" for f in out["findings"]) or "- no findings")
                st.markdown(f"> {out['email'] or 'No email drafted.'}".replace("\n", "\n> "))
                answers = []
                for i, question in enumerate(q.QUESTIONS):
                    before = item.get("answers", [])
                    start = before[i] if i < len(before) else "–"
                    answers.append(
                        st.radio(
                            question,
                            q.ANSWERS,
                            index=q.ANSWERS.index(start),
                            horizontal=True,
                            key=f"qual-{reviewer}-{picked}-{student}-{i}",
                        )
                    )
                cause = st.selectbox(
                    "Cause, if something is wrong",
                    ["", *q.CAUSES],
                    index=(["", *q.CAUSES].index(item["cause"]) if item.get("cause") else 0),
                    key=f"qual-{reviewer}-{picked}-{student}-cause",
                )
                note = st.text_input(
                    "One line of why",
                    value=item.get("note", ""),
                    key=f"qual-{reviewer}-{picked}-{student}-note",
                )
                entered[q.key(picked, student)] = {
                    "answers": answers,
                    "cause": cause,
                    "note": note,
                }
        if st.form_submit_button("Save this session's answers", type="primary"):
            q.save(stamp, reviewer, {**saved, **entered})
            st.success("Saved.")
            st.rerun()


def comparison(stamp: str) -> None:
    found = q.reviewers(stamp)
    if len(found) < 2:
        st.caption(
            f"{len(found)} reviewer(s) saved so far. Once two have finished, this shows where "
            "they agree."
        )
        return
    first, second = found[0], found[1]
    result = q.compare(first, second)
    if not result["compared"]:
        st.caption("The two reviewers have no answered outputs in common yet.")
        return
    st.markdown(
        f"**{first['reviewer']}** and **{second['reviewer']}** gave the same answer on "
        f"{result['same']} of {result['compared']} questions "
        f"({result['same'] / result['compared']:.0%}). Disagreements are the places where "
        "'fair' or 'traceable' is a judgement call."
    )
    if result["differ"]:
        st.dataframe(
            [
                {
                    "Output": d["output"],
                    "Question": d["question"],
                    first["reviewer"]: d["first"],
                    second["reviewer"]: d["second"],
                }
                for d in result["differ"]
            ],
            hide_index=True,
            width="stretch",
        )


def qualitative_section() -> None:
    st.subheader("Qualitative review: read the outputs")
    latest = q.latest_run()
    if latest is None:
        st.markdown(
            "Not available yet: it reads the outputs of a whole-system run "
            "(`python eval/system_eval.py`)."
        )
        return
    stamp, run = latest
    st.markdown(
        "The checks above are automatic. Whether a score is **fair** or an email **kind** needs a "
        "person. Read each student's findings and email from the latest run, answer the five "
        "questions, and tag a cause if something is wrong. A second reviewer does the same "
        "separately, and the comparison shows where two people disagree."
    )
    name = st.text_input("Your name", key="qual-reviewer", placeholder="e.g. Saurabh")
    if q.reviewer_slug(name):
        review_form(stamp, run, name)
        mine = q.summary(q.load(stamp, name).get("reviews", {}))
        if mine["reviewed"]:
            causes = ", ".join(f"{c} ×{n}" for c, n in mine["causes"].items()) or "none tagged"
            st.caption(
                f"{mine['reviewed']} outputs saved by you, {mine['withProblem']} with a problem. "
                f"Causes: {causes}."
            )
    else:
        st.caption("Enter your name to start. Your answers are saved under it.")
    with st.expander("Compare two reviewers"):
        comparison(stamp)
