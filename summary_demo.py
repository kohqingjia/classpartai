import json
import os
from types import SimpleNamespace

import streamlit as st
from dotenv import load_dotenv
# from groq import Groq
from openai import OpenAI

from classpartai.summary.agent import analyse_session
from classpartai.summary.ui import render_session_summary

load_dotenv()


def build_transcript(raw_text):
    turns = []

    for line in raw_text.splitlines():
        line = line.strip()

        if not line or ":" not in line:
            continue

        speaker_name, text = line.split(":", 1)
        speaker_name = speaker_name.strip()
        text = text.strip()

        if not speaker_name or not text:
            continue

        is_professor = speaker_name.lower() in {"professor", "prof", "instructor"}

        turns.append(
            SimpleNamespace(
                id=f"t{len(turns) + 1}",
                speaker=SimpleNamespace(
                    kind="professor" if is_professor else "student",
                    studentId=None if is_professor else speaker_name,
                ),
                text=text,
                startMs=len(turns) * 1000,
            )
        )

    return SimpleNamespace(turns=turns)


def generate_json(system_prompt, user_prompt):
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    # client = Groq(api_key=os.environ["GROQ_API_KEY"])

    response = client.chat.completions.create(
        model="gpt-4.1-mini",
        # model="openai/gpt-oss-20b",
        messages=[
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    return json.loads(response.choices[0].message.content)


st.title("ClassPart AI — Session Summary")

st.write("Enter a seminar transcript to generate an AI-powered professor briefing.")

raw_transcript = st.text_area(
    "Seminar Transcript",
    height=250,
    placeholder=(
        "Professor: What is Agentic RAG?\n"
        "Tina: Agentic RAG allows an agent to decide when to retrieve.\n"
        "John: Repeated retrieval may increase latency."
    ),
)

if st.button("Generate Session Summary"):
    transcript = build_transcript(raw_transcript)

    if not transcript.turns:
        st.error("Enter at least one contribution using 'Speaker: contribution'.")
    elif not os.getenv("OPENAI_API_KEY"):
        st.error("OPENAI_API_KEY is missing from your .env file.")
    # elif not os.getenv("GROQ_API_KEY"):
    #     st.error("GROQ_API_KEY is missing from your .env file.")
    else:
        try:
            with st.spinner("Analysing seminar..."):
                result = analyse_session(
                    transcript=transcript,
                    generate_json=generate_json,
                )

            st.session_state["summary_result"] = result

        except Exception as error:
            st.error(f"Summary generation failed: {error}")

if "summary_result" in st.session_state:
    render_session_summary(st.session_state["summary_result"])
