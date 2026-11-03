from datetime import date

import pytest

from classpartai.research.materials import (
    Chunk,
    lesson_for_date,
    load_materials,
    read_pages,
    split_into_chunks,
)
from classpartai.research.store import VectorStore

from .conftest import SAMPLE
from .fakes import HashEmbedder


def test_lesson_on_the_day_and_later_in_the_week(schedule):
    assert (
        lesson_for_date(schedule, "2026-09-01")["topic"]
        == "Platform competition and market tipping"
    )
    later = lesson_for_date(schedule, date(2026, 9, 4))
    assert later["week"] == 3 and "multi-homing" in later["key_concepts"]
    assert lesson_for_date(schedule, "2026-07-01") is None


def test_chunks_overlap():
    words = [f"w{i}" for i in range(25)]
    chunks = split_into_chunks(" ".join(words), window=10, overlap=3)
    assert chunks[1].split()[:3] == words[7:10]
    assert chunks[-1].split()[-1] == "w24"


def test_slides_and_readings_keep_deck_page_and_week():
    chunks = load_materials(SAMPLE)
    slide = next(c for c in chunks if c.doc.endswith("week02-network-effects.md") and c.page == 2)
    assert slide.kind == "slides" and slide.week == 2
    assert slide.source() == "week02 network effects (slides), slide 2"
    reading = next(
        c for c in chunks if c.doc.endswith("week03-when-markets-tip.md") and c.page == 2
    )
    assert reading.kind == "reading" and reading.source().endswith("(reading), p. 2")
    assert len({c.id for c in chunks}) == len(chunks)


def test_pptx_slides_are_numbered(tmp_path):
    from pptx import Presentation

    deck = Presentation()
    for title in ("Intro", "Multi-homing weakens tipping"):
        slide = deck.slides.add_slide(deck.slide_layouts[1])
        slide.shapes.title.text = title
    path = tmp_path / "week03-deck.pptx"
    deck.save(path)
    assert read_pages(path)[1] == (2, "Multi-homing weakens tipping")


def _tiny_pdf(text: str) -> bytes:
    """A one-page PDF with one line of text, written by hand so the test needs no extra library."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return bytes(out)


def test_pdf_pages_are_numbered(tmp_path):
    path = tmp_path / "reading.pdf"
    path.write_bytes(_tiny_pdf("Subsidies are hard to withdraw."))
    page, text = read_pages(path)[0]
    assert page == 1 and "Subsidies are hard to withdraw" in text


def test_store_finds_exact_terms_filters_by_week_and_round_trips(store, tmp_path):
    hits = store.search("multi-homing", k=3)
    assert any("multi-homing" in h.chunk.text.lower() for h in hits)
    week4 = store.search("network effects", week=4, k=10)
    assert {h.chunk.week for h in week4} <= {4, None}

    store.save(tmp_path)
    assert len(VectorStore.load(tmp_path, HashEmbedder()).chunks) == len(store.chunks)

    class Other(HashEmbedder):
        name = "test:other"

    with pytest.raises(ValueError, match="Rebuild"):
        VectorStore.load(tmp_path, Other())


def test_context_text_carries_the_source():
    chunk = Chunk("x", "body", "reading", "readings/w.md", "week03 tip", week=3, page=2)
    assert chunk.context_text() == "[week03 tip (reading), p. 2, week 3] body"
