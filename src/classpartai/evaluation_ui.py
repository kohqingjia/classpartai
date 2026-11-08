"""The Evaluation page: what ClassPart AI costs against a teaching assistant, and every
comparison the team has run, read from the committed results in eval/results/."""

import json
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

import streamlit as st

from classpartai import costing
from classpartai.config import REPO_ROOT
from classpartai.experiments_ui import judge_markdown
from classpartai.qualitative_ui import qualitative_section

RESULTS = REPO_ROOT / "eval" / "results"
AUDITOR_OFFLINE = RESULTS / "auditor-tool-descriptions-offline.json"

_BAR_CSS = """
<style>
.cmp { margin:8px 0 4px; }
.cmp-row { display:grid; grid-template-columns:132px minmax(0,1fr) 96px; gap:12px;
  align-items:center; margin:8px 0; font-size:13px; }
.cmp-label { color:var(--text-color, #ededed); }
.cmp-track { height:24px; background:rgba(237,237,237,.06); border-radius:6px; display:flex;
  overflow:hidden; }
.cmp-seg { height:100%; }
.cmp-num { text-align:right; font-variant-numeric:tabular-nums;
  font-family:ui-monospace,monospace; }
.cmp-key { display:flex; gap:16px; font-size:12px; color:#d4d4d8; margin-top:4px; }
.cmp-key span { display:inline-flex; gap:6px; align-items:center; }
.cmp-dot { width:8px; height:8px; border-radius:2px; display:inline-block; }
</style>
"""
TA, SERVER, MODEL = "#8c8c93", "#c4c4ca", "#e8b03c"  # the software's model cost is the accent


def md(text: str) -> None:
    """st.markdown, with "$" kept as a dollar sign (Streamlit reads "$...$" as LaTeX)."""
    st.markdown(text.replace("$", "\\$"))


def caption(text: str) -> None:
    st.caption(text.replace("$", "\\$"))


def interval(passed: int, total: int) -> str:
    """A rate with its range: 20 items cannot pin a rate down (Wilson 95%)."""
    if not total:
        return "none run"
    z, p = 1.96, passed / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * (p * (1 - p) / total + z * z / (4 * total * total)) ** 0.5 / (1 + z * z / total)
    return f"{passed} of {total} ({p:.0%}, plausibly {centre - half:.0%} to {centre + half:.0%})"


def sgd(x: float) -> str:
    return f"S${x:,.2f}"


def _load(name: str) -> dict | None:
    path = RESULTS / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _bar(rows: list[tuple[str, list[tuple[float, str]]]], scale: float) -> str:
    html = [_BAR_CSS, '<div class="cmp">']
    for label, parts in rows:
        total = sum(v for v, _ in parts)
        segs = "".join(
            f'<div class="cmp-seg" style="width:{100 * v / scale:.2f}%;background:{c}"></div>'
            for v, c in parts
        )
        html.append(
            f'<div class="cmp-row"><div class="cmp-label">{label}</div>'
            f'<div class="cmp-track">{segs}</div><div class="cmp-num">{sgd(total)}</div></div>'
        )
    html.append(
        '<div class="cmp-key">'
        f'<span><i class="cmp-dot" style="background:{TA}"></i>TA pay</span>'
        f'<span><i class="cmp-dot" style="background:{SERVER}"></i>Server (Listener + app)</span>'
        f'<span><i class="cmp-dot" style="background:{MODEL}"></i>Model calls (OpenAI)</span>'
        "</div></div>"
    )
    return "".join(html)


def assumptions_form() -> costing.Assumptions:
    d = costing.Assumptions()
    with st.expander("Assumptions (change them)", expanded=False):
        c = st.columns(3)
        a = replace(
            d,
            lessons=c[0].number_input("Lessons per semester", 1, 30, d.lessons),
            lesson_hours=c[0].number_input("Hours per lesson", 0.5, 6.0, d.lesson_hours, 0.5),
            students=c[1].number_input("Students in the class", 1, 200, d.students),
            contributions=c[1].number_input(
                "Times students speak per lesson",
                1,
                400,
                d.contributions,
                help="Not everyone speaks: about 20 contributions in a 40-student class.",
            ),
            server_sgd_month=c[2].number_input(
                "Server, S$ per month",
                0.0,
                600.0,
                d.server_sgd_month,
                5.0,
                help="An estimate for a 4-vCPU cloud server, which the Listener needs.",
            ),
            semester_months=c[2].number_input(
                "Months the server runs", 1.0, 12.0, d.semester_months, 0.5
            ),
            sgd_per_usd=c[0].number_input(
                "Exchange rate for OpenAI's bill (S$ per US$)", 1.0, 2.0, d.sgd_per_usd, 0.01
            ),
            ta_sgd_semester=c[1].number_input(
                "TA pay, S$ per semester", 0.0, 10000.0, d.ta_sgd_semester
            ),
            review_minutes_per_contribution=c[2].number_input(
                "Professor review, minutes per contribution",
                0.0,
                10.0,
                d.review_minutes_per_contribution,
                0.5,
            ),
        )
    return a


def cost_section(records=None) -> None:
    st.subheader("Cost: ClassPart AI or a teaching assistant")
    m = costing.measured(records=records)
    if m is None:
        st.info("No measured run yet: run eval/cost_measure.py on the server.")
        return
    if m["source"] == "ledger" and m["run"].get("status") == "pooled":
        run = m["run"]
        st.success(
            f"Measured on real runs: the newest finished assessment of each of "
            f"{len(run['sessions'])} demo seminars ({run['students']} students in all) cost "
            f"US\\${run['usd']:.2f} together. The figures below are built from those runs.",
            icon=":material/check_circle:",
        )
    elif m["source"] == "ledger":
        st.success(
            f"Measured from the app's own latest complete run (`{m['run']['id'][:8]}`, "
            f"{m['run']['recordedAt'][:10]}), so it follows the code as it is now.",
            icon=":material/check_circle:",
        )
    issues = costing.problems(m["run"])
    if issues:
        st.warning(
            "The committed sample run is not a fair basis for a lesson's cost: "
            + "; ".join(issues)
            + ". The numbers below are therefore rough. Run a full assessment on the server and "
            "they switch to that run automatically.",
            icon=":material/warning:",
        )
    a = assumptions_form()
    e = costing.estimate(m, a)
    md(
        f"A TA paid **{sgd(a.ta_sgd_semester)}** a semester for {a.lessons} lessons of "
        f"{a.lesson_hours:g} hours costs **{sgd(e['ta_per_lesson'])}** a lesson. Below is "
        f"ClassPart AI for the same semester, with {a.contributions} student contributions "
        f"a lesson in a class of {a.students}."
    )
    cols = st.columns(4)
    cols[0].metric("ClassPart AI, semester", sgd(e["software_semester"]))
    cols[1].metric("TA, semester", sgd(e["ta_semester"]))
    cols[2].metric("Model calls, per lesson", sgd(e["model_per_lesson"]))
    cols[3].metric(
        "Difference, semester",
        sgd(abs(e["saving_semester"])),
        "cheaper than a TA" if e["saving_semester"] >= 0 else "dearer than a TA",
        delta_color="normal" if e["saving_semester"] >= 0 else "inverse",
    )
    scale = max(e["ta_semester"], e["software_semester"]) or 1
    st.html(
        _bar(
            [
                ("Teaching assistant", [(e["ta_semester"], TA)]),
                (
                    "ClassPart AI",
                    [(e["server_semester"], SERVER), (e["model_semester"], MODEL)],
                ),
            ],
            scale,
        )
    )
    caption(
        f"Break-even: the model calls could cost up to {sgd(e['break_even_model_per_lesson'])} "
        "a lesson before the software stops being cheaper."
    )

    md("**Time per lesson**")
    md(
        "| | ClassPart AI | Note |\n|---|---|---|\n"
        f"| Listener (transcribe, who spoke) | {e['listener_hours_per_lesson']:.1f} h of CPU | "
        "unattended, on the server |\n"
        f"| Assessment (agents) | {e['assessment_minutes_per_lesson']:.0f} min | unattended |\n"
        f"| Professor review | {e['review_minutes_per_lesson']:.0f} min | not priced: the "
        "professor approves every draft either way |"
    )

    run = m["run"]
    with st.expander("What was measured"):
        md(
            f"One real assessment run on **{run['session']}** ({run['recordedAt'][:10]}, "
            f"`{run['id'][:8]}`, model `{run['model']}`, stop: {run['stopReason']}): "
            f"{run['contributions']} student contributions from {run['students']} students, "
            f"{run['audio_seconds']} s of audio, {run['modelCalls']} model calls, "
            f"{run['seconds']:.0f} s, **S${run['usd'] * a.sgd_per_usd:.4f}** "
            f"(S${run['usd'] * a.sgd_per_usd / run['contributions']:.4f} per contribution)."
        )
        md(
            "| Agent | Calls | Input tokens | of which cached | Output tokens | S$ |\n"
            "|---|---|---|---|---|---|\n"
            + "\n".join(
                f"| {agent} | {u['calls']:.0f} | {u['input_tokens']:,.0f} | "
                f"{u['cached_tokens']:,.0f} | {u['output_tokens']:,.0f} | "
                f"{u['usd'] * a.sgd_per_usd:.4f} |"
                for agent, u in sorted(run["byAgent"].items(), key=lambda x: -x[1]["usd"])
            )
        )
        if run.get("note"):
            caption(run["note"])
        lst = m["listener"]
        md(
            f"Listener: {lst['pipeline_seconds']:.0f} s for {lst['audio_seconds']:.0f} s of "
            f"audio ({lst['pipeline_seconds'] / lst['audio_seconds']:.1f}× real time, "
            f"{lst['cpu']}), from the Listener eval. Model prices: "
            f"`{m['prices']['source']}`, converted at S${a.sgd_per_usd:.2f} per US$."
        )
    with st.expander("What this leaves out"):
        md(
            "- **Extrapolated from a short demo.** Cost is scaled by the number of student "
            "contributions. A 3-hour recording would not fit one run: the guardrail eval's "
            "420-turn transcript stopped at the run's budget with no draft. A full lesson "
            "would be assessed in segments, so treat this as an estimate.\n"
            "- **A TA does more than score.** Attending, answering questions and judging "
            "things a recording can't hear aren't priced here.\n"
            "- **The professor still reviews.** ClassPart AI drafts; a person approves every "
            "score and email, with or without a TA.\n"
            "- **Prices are estimates.** Model prices come from `data/model_prices.json`; the "
            "OpenAI bill is the source of truth. The server price is an estimate."
        )


def research_section() -> None:
    d = _load("research-is469-library.json")
    if not d:
        return
    st.subheader("Research: single-pass RAG or the agent (Tasmin's Research agent)")
    sp, ag = d["single_pass"]["summary"], d["agentic"]["summary"]
    rate = costing.Assumptions().sgd_per_usd
    sp, ag = ({**x, "sgd": x["usd"] * rate} for x in (sp, ag))
    rows = [
        ("Correct verdict", "correctness_ok", "{:.0%}"),
        ("Context precision", "context_precision", "{:.0%}"),
        ("Found the gold passage", "gold_hit", "{:.0%}"),
        ("Quotes are exact", "quoted", "{:.0%}"),
        ("Routed correctly (course or web)", "routed_correctly", "{:.0%}"),
        ("Model calls per item", "llm_calls", "{:.1f}"),
        ("Seconds per item", "seconds", "{:.0f}"),
        ("S$ per item", "sgd", "{:.4f}"),
    ]
    fmt = lambda f, v: "—" if v is None else f.format(v)  # noqa: E731
    md(
        "| | Single pass | Agent |\n|---|---|---|\n"
        + "\n".join(f"| {label} | {fmt(f, sp[k])} | {fmt(f, ag[k])} |" for label, k, f in rows)
    )
    cfg = d["config"]
    caption(
        f"{len(d['agentic']['rows'])} labelled IS469 contributions, model {cfg['model']}. "
        "The agent is more often right and more precise, for about 6× the cost and 5× the time. "
        "Full table: eval/results/research-is469-library.md"
    )


def listener_section() -> None:
    d = _load("listener-20261107.json")
    if not d:
        return
    st.subheader("Listener: who spoke, before and after the fixes (Tina's pipeline)")

    def row(label, t):
        s, p = t["student"], t["professor"]
        return (
            f"| {label} | {t['wrong_person']} | {s['correct']}/{s['lines']} | "
            f"{p['correct']}/{p['lines']} |"
        )

    md(
        "| | Lines given to the wrong person | Student lines right | Professor lines right |\n"
        "|---|---|---|---|\n"
        + "\n".join(
            [
                row("Before (turn-level match)", d["A"]["totals"]),
                row("Word timings + per-line check", d["default"]["W+veto"]["totals"]),
                row("+ whole-turn check (shipped)", d["shipped"]["totals"]),
            ]
        )
    )
    wer = next(iter(d["wer"].values()))
    caption(
        f"Seven demo recordings in our real voices. Word error rate {wer:.1%}. Full results "
        "and how it decides: eval/results/listener-20261107.md and How it works."
    )


def _case_history(files: list[Path]) -> dict[str, tuple[int, int]]:
    """Per case, how many saved guardrail runs caught it, out of those that included it."""
    seen: dict[str, list[bool]] = {}
    for f in files:
        for c in json.loads(f.read_text(encoding="utf-8"))["cases"]:
            seen.setdefault(c["case"], []).append(bool(c["caught"]))
    return {case: (sum(r), len(r)) for case, r in seen.items()}


def guardrails_section() -> None:
    files = sorted(RESULTS.glob("guardrails-*.json"))
    if not files:
        return
    d = json.loads(files[-1].read_text(encoding="utf-8"))
    st.subheader("Guardrails: attacks on the whole workflow")
    md(
        f"**{d['caught']}/{len(d['cases'])} caught** · model {d['model']} · "
        f"S${d['totalUsd'] * costing.Assumptions().sgd_per_usd:.2f} for the run"
    )
    md(
        "| Attack | Caught | Guardrail |\n|---|---|---|\n"
        + "\n".join(
            f"| {c['attack'].replace('|', '/')} | {c['caught']} | {c['guardrail']} |"
            for c in d["cases"]
        )
    )
    history = _case_history(files)
    if len(files) > 1:
        md(
            "Runs saved so far, per case (Judge scoring varies between runs, so one pass is not "
            "proof):"
            + chr(10) * 2
            + chr(10).join(f"- {c}: caught in {k} of {n} runs" for c, (k, n) in history.items())
        )
    caption(f"Full observations: eval/results/{Path(files[-1]).with_suffix('.md').name}")


def system_section() -> None:
    files = sorted(RESULTS.glob("system-*.json"))
    st.subheader("Whole system: seven class sessions, transcript to emails")
    if not files:
        md(
            "Not run yet. `eval/system_eval.py` runs each scripted demo seminar through the "
            "Coordinator and every agent it calls, then checks that the session finished, that "
            "its edge case was handled (a silent student, spoken injection, a guest...), that "
            "the agents handed work to each other, and what each cost."
        )
        st.code("uv run python eval/system_eval.py", language="bash")
        return
    d = json.loads(files[-1].read_text(encoding="utf-8"))
    sessions = d["sessions"]
    passed, total = sum(x["passed"] for x in sessions), sum(x["total"] for x in sessions)
    md(
        f"**{interval(passed, total)} automatic checks passed** over {len(sessions)} sessions · "
        f"model {d['model']} · "
        f"S${d['totalUsd'] * costing.Assumptions().sgd_per_usd:.2f} for the run"
    )
    md(
        "| Session | Checks | What it tests | Not passed |\n|---|---|---|---|\n"
        + "\n".join(
            f"| {x['id']} | {x['passed']}/{x['total']} | {x['case'].replace('|', '/')} | "
            + ("; ".join(c["name"] for c in x["checks"] if not c["passed"]) or "none")
            + " |"
            for x in sessions
        )
    )
    caption(
        "Automatic signals, not a grade: what a person concludes from reading the same outputs "
        f"is the qualitative half. Full detail: eval/results/{files[-1].with_suffix('.md').name}"
    )


def auditor_section() -> None:
    if not AUDITOR_OFFLINE.exists():
        return
    d = json.loads(AUDITOR_OFFLINE.read_text(encoding="utf-8"))
    st.subheader("Auditor: do better tool descriptions help? (before the Auditor was merged)")
    agg: dict = defaultdict(lambda: [0, 0, 0, 0])
    for r in d["runs"]:
        a = agg[r["variant"]]
        a[0] += 1
        a[1] += r["matches_authored_expectation"]
        a[2] += r["invalid_calls"]
        a[3] += r["usage"]["model_calls"]
    names = {
        "original": "Original tools",
        "description_only": "Clearer descriptions",
        "description_and_recovery": "+ recovery hints",
        "all_three": "+ all three changes",
    }
    md(
        "| Variant | Expected verdict | Invalid calls | Model calls |\n|---|---|---|---|\n"
        + "\n".join(
            f"| {names.get(v, v)} | {n_ok}/{n} | {bad} | {calls} |"
            for v, (n, n_ok, bad, calls) in agg.items()
        )
    )
    caption(
        "One change at a time, on five fictional cases. Run against a scripted test double, "
        "not a live model, so it shows the harness behaves as designed, not model accuracy. "
        "A result kept from the Auditor's original stand-alone harness (eval/results/"
        "auditor-tool-descriptions-offline.json); the merged Auditor has no such variants."
    )


def judge_section() -> None:
    st.subheader("Judge: agreement with human scores (Saurabh's Judge agent)")
    table_md = judge_markdown()
    if table_md:
        md(table_md)
        return
    md("Not run yet: `eval/judge_eval.py` scores the Judge against 20 hand-scored answers.")
    st.code("python eval/judge_eval.py", language="bash")


def evaluation_view(records=None) -> None:
    st.title("Evaluation")
    st.markdown(
        '<p class="muted">What ClassPart AI costs against a teaching assistant, and every '
        "comparison the team has run. Each table is read from the committed results in "
        "eval/results.</p>",
        unsafe_allow_html=True,
    )
    cost_section(records)
    system_section()
    qualitative_section()
    research_section()
    judge_section()
    auditor_section()
    listener_section()
    guardrails_section()
