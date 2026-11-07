"""The How it works page shows real code: every snippet must still exist in the source."""

import pytest

from classpartai.snippets import AGENTS, TOPICS, Snippet, source

ALL = [s for _, snippets in TOPICS for s in snippets]


@pytest.mark.parametrize("snippet", ALL, ids=lambda s: f"{s.path}:{'+'.join(s.names)}")
def test_every_snippet_resolves(snippet):
    found = source(snippet)
    assert found is not None, f"{snippet.names} not found in {snippet.path}: update snippets.py"
    code, line = found
    assert line >= 1
    for name in snippet.names:
        assert name.rsplit(".", 1)[-1] in code


def test_snippet_keeps_comments_and_methods(tmp_path):
    (tmp_path / "m.py").write_text(
        "# the window\nSIZE = 3\n\n\nclass A:\n    def f(self):\n        return SIZE\n"
    )
    code, line = source(Snippet("t", "m.py", ("SIZE", "A.f"), ""), root=tmp_path)
    assert line == 1
    assert code == "# the window\nSIZE = 3\n\ndef f(self):\n    return SIZE"
    assert source(Snippet("t", "m.py", ("MISSING",), ""), root=tmp_path) is None
    assert source(Snippet("t", "nope.py", ("SIZE",), ""), root=tmp_path) is None


def tools_of(name):
    return {t.name for a in AGENTS if a.name == name for t in a.tools}


@pytest.mark.parametrize("tool", [t for a in AGENTS for t in a.tools], ids=lambda t: t.name)
def test_every_catalogued_tool_shows_its_code(tool):
    found = source(tool.snippet)
    assert found is not None, f"{tool.names} not found in {tool.path}: update snippets.AGENTS"
    assert tool.does and tool.takes and tool.returns


@pytest.mark.parametrize(
    "snippet", [c for a in AGENTS for c in a.code], ids=lambda c: f"{c.path}:{c.names}"
)
def test_every_part_without_tools_shows_its_code(snippet):
    assert source(snippet) is not None, f"{snippet.names} not found in {snippet.path}"


def test_every_part_shows_tools_or_code():
    assert all(a.tools or a.code for a in AGENTS)


def test_the_catalogue_lists_exactly_the_tools_each_agent_has():
    from classpartai.auditor_agent.harness import TOOLS
    from classpartai.participation.coordinator import COORDINATOR_TOOLS
    from classpartai.research.tools import ResearchTools

    assert tools_of("Coordinator") == {t.name for t in COORDINATOR_TOOLS}
    assert tools_of("Auditor") == {t["function"]["name"] for t in TOOLS}
    research = ResearchTools.__new__(ResearchTools)
    research.web = object()  # as if a web search key were set, so search_web is offered
    assert tools_of("Research") == {t["function"]["name"] for t in research.schemas()}


def test_a_branch_snippet_shows_only_that_tool(tmp_path):
    (tmp_path / "m.py").write_text(
        "def loop(call):\n"
        "    if call.name == 'a':\n"
        "        x = 1\n"
        "    elif call.name == 'b':\n"
        "        # b's work\n"
        "        x = 2\n"
        "    else:\n"
        "        x = 3\n"
    )
    code, line = source(Snippet("t", "m.py", ("loop#b",), ""), root=tmp_path)
    assert line == 4
    assert code == "elif call.name == 'b':\n    # b's work\n    x = 2"
    assert source(Snippet("t", "m.py", ("loop#c",), ""), root=tmp_path) is None
