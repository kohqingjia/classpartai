"""The How it works page shows real code: every snippet must still exist in the source."""

import pytest

from classpartai.snippets import TOPICS, Snippet, source

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
