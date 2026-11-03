import json

import pytest

from classpartai.assessment import Document
from classpartai.library import Library
from classpartai.retrieval import searches_of

SLIDES = (
    b"# Slide 1\nAgentic RAG retrieves again when needed.\n\n# Slide 2\nEach round adds latency.\n"
)


def test_upload_replace_and_remove(tmp_path):
    library = Library(tmp_path)
    doc = library.add("Week 10 - Agentic RAG.md", SLIDES)
    Document.model_validate(doc)
    assert doc["source"] == "Course library: Week 10 - Agentic RAG.md"
    assert "latency" in " ".join(p["text"] for p in doc["passages"])
    library.add("Week 10 - Agentic RAG.md", SLIDES + b"\n# Slide 3\nCap the retries.\n")
    assert len(library.documents()) == 1  # same file name replaces
    other = library.add("notes.txt", b"Fine-tuning changes the weights.")
    assert other["id"] != doc["id"]
    library.remove("notes.txt")
    assert [e["file"] for e in library.entries()] == ["Week 10 - Agentic RAG.md"]
    assert not (tmp_path / "files" / "notes.txt").exists()


def test_rejects_unsupported_and_empty_files(tmp_path):
    library = Library(tmp_path)
    with pytest.raises(ValueError, match="supported types"):
        library.add("malware.exe", b"MZ")
    with pytest.raises(ValueError, match="no readable text"):
        library.add("empty.md", b"   ")
    assert library.documents() == []


def test_searches_of_reads_the_course_agents_actions():
    progress = {
        "actions": [
            {
                "tool": "search_course_passages",
                "outcome": "ok",
                "arguments": json.dumps({"query": "agentic latency"}),
                "resultReferences": ["w10:1:p3"],
            },
            {"tool": "finish_evidence", "outcome": "ok", "arguments": "{}"},
        ]
    }
    assert searches_of(progress) == [
        {"query": "agentic latency", "hits": [{"passageId": "w10:1:p3", "score": None}]}
    ]


def test_vault_page_keeps_slide_text_as_data():
    from classpartai.ui import vault_html

    library_doc = {
        "id": "w10",
        "version": "1",
        "title": "Week 10",
        "source": "Course library: w10.md",
        "passages": [{"id": "p1", "page": 1, "text": "</script><script>alert(1)</script>"}],
    }
    page = vault_html(
        [library_doc], [{"query": "</script>", "hits": [{"passageId": "w10:1:p1", "score": 1.0}]}]
    )
    assert page.count("</script>") == 2  # only the page's own two script tags
    assert "alert(1)" in page  # still there, as escaped JSON text
