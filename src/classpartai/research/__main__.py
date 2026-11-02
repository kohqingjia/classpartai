"""Command line for the Research agent.

uv run python -m classpartai.research check        # is everything set up? (models, files, index)
uv run python -m classpartai.research ingest       # embed the lecture files into the index
uv run python -m classpartai.research run "<student's answer>" --question "<professor's question>" \
    --date 2026-09-08 --trajectory
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from classpartai import config


def _hint(exc: Exception) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if config.LLM_PROVIDER == "ollama":
        if "Connection" in text or "connect" in text.lower():
            return f"{text}\n      -> Is the Ollama app running? Open it, or run `ollama serve`."
        if "not found" in text.lower() or "404" in text:
            return f"{text}\n      -> Download the model: `ollama pull <model name above>`."
        if "tool" in text.lower():
            return f"{text}\n      -> This model cannot call tools. Try OLLAMA_MODEL=qwen3:8b."
    elif "api_key" in text or "401" in text or "Authentication" in text:
        return (
            f"{text}\n      -> Put your key in .env as OPENAI_API_KEY, or set LLM_PROVIDER=ollama."
        )
    return text


def check() -> bool:
    """Try each piece in turn and report what works, with a hint for anything that does not."""
    from classpartai.llm import OpenAIChat, OpenAIEmbedder
    from classpartai.research.materials import load_materials, load_schedule
    from classpartai.research.store import VectorStore
    from classpartai.research.web import default_web_search

    ok = True

    def report(name: str, fn) -> None:
        nonlocal ok
        try:
            print(f"  ok    {name}: {fn()}")
        except Exception as exc:  # report every failure, then carry on to the next check
            ok = False
            print(f"  FAIL  {name}: {_hint(exc)}")

    print(f"Provider: {config.LLM_PROVIDER}")
    try:
        chat, embedder = OpenAIChat(), OpenAIEmbedder()
    except Exception as exc:  # e.g. no OPENAI_API_KEY: report it and check the files anyway
        ok, chat, embedder = False, None, None
        print(f"  FAIL  models: {_hint(exc)}")
    if embedder is not None:
        report(
            "embedding model", lambda: f"{embedder.name}, {embedder.encode(['x']).shape[1]} dims"
        )

    def tool_call() -> str:
        tool = {
            "type": "function",
            "function": {
                "name": "get_lesson_context",
                "description": "Get the seminar topic for a date.",
                "parameters": {
                    "type": "object",
                    "properties": {"date": {"type": "string"}},
                    "required": ["date"],
                },
            },
        }
        prompt = "What was the seminar topic on 2026-09-08? Use the tool."
        turn = chat.complete([{"role": "user", "content": prompt}], tools=[tool])
        if not turn.tool_calls:
            raise RuntimeError(
                f"{chat.name} answered without calling the tool, so it cannot drive the agent. "
                "Try a larger model."
            )
        return f"{chat.name} called {turn.tool_calls[0].name}({turn.tool_calls[0].arguments})"

    if chat is not None:
        report("chat model with tools", tool_call)

    def files() -> str:
        chunks = load_materials(config.MATERIALS_DIR, load_schedule(config.COURSE_DIR))
        docs = sorted({(c.week or 0, c.doc) for c in chunks})
        for week, doc in docs:
            print(f"          week {week or '-':>2}  {doc}")
        return f"{len(docs)} files, {len(chunks)} chunks in {config.MATERIALS_DIR}"

    report("lecture files", files)
    if embedder is not None:
        report(
            "index",
            lambda: (
                f"{len(VectorStore.load(config.INDEX_DIR, embedder).chunks)} chunks in "
                f"{config.INDEX_DIR}"
            ),
        )
    web = default_web_search()
    status = "Tavily" if web else "off (no TAVILY_API_KEY)"
    print(f"  {'ok' if web else 'info':5s} web search: {status}")
    print("\nAll set." if ok else "\nFix the FAIL lines above, then run this again.")
    return ok


def ingest(materials_dir: str, course_dir: str) -> None:
    from classpartai.llm import OpenAIEmbedder
    from classpartai.research.materials import load_materials, load_schedule
    from classpartai.research.store import VectorStore

    chunks = load_materials(materials_dir, load_schedule(course_dir))
    embedder = OpenAIEmbedder()
    print(f"Embedding {len(chunks)} chunks with {embedder.name}...")
    VectorStore.build(chunks, embedder).save(config.INDEX_DIR)
    print(f"Indexed {len(chunks)} chunks from {materials_dir} into {config.INDEX_DIR}")
    counts = Counter((c.week or 0, c.kind, c.doc) for c in chunks)
    for (week, kind, doc), n in sorted(counts.items()):
        print(f"  week {week or '-':>2}  {kind:7s} {n:>3} chunks  {doc}")


def run(
    text: str, date: str, question: str | None, judge: bool, as_json: bool, show_trajectory: bool
) -> None:
    from classpartai.research.agent import ResearchAgent

    agent = ResearchAgent.from_config()
    if judge:
        pack = agent.answer_question(text, date)
    else:
        pack = agent.run(text, date=date, question=question)
    if as_json:
        print(pack.to_json())
        return
    print(pack.brief())
    print(f"\nneeds_review={pack.needs_review} stop={pack.stop_reason} usage={pack.usage}")
    for note in pack.notes:
        print(f"note: {note}")
    if show_trajectory:
        print("\nTrajectory:")
        for s in pack.trajectory:
            print(f"  {s['step']:>2} {s['tool']}({json.dumps(s['args'])}) -> {s['result']}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m classpartai.research")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="test the models, lecture files and index, with fix-it hints")
    p = sub.add_parser("ingest", help="chunk and embed the course's slides, readings and labs")
    p.add_argument("--materials", default=config.MATERIALS_DIR, help="folder of lecture files")
    p.add_argument("--course", default=config.COURSE_DIR, help="folder with schedule.json")
    p = sub.add_parser("run", help="research a student's answer to a professor's question")
    p.add_argument("text", help="the student's answer (or an unprompted comment)")
    p.add_argument("--question", help="the professor's question the student was answering")
    p.add_argument("--date", required=True, help="session date, YYYY-MM-DD")
    p.add_argument("--judge", action="store_true", help="treat the text as a Judge's question")
    p.add_argument("--json", action="store_true", help="print the full EvidencePack")
    p.add_argument("--trajectory", action="store_true", help="print every tool call")
    args = parser.parse_args(argv)
    try:
        if args.command == "check":
            sys.exit(0 if check() else 1)
        elif args.command == "ingest":
            ingest(args.materials, args.course)
        else:
            run(args.text, args.date, args.question, args.judge, args.json, args.trajectory)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
