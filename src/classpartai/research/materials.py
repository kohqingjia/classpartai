"""Course materials: the weekly schedule, and slides, readings and labs split into citable chunks.

Two folders, which can be the same one:

    course folder (COURSE_DIR, committed), e.g. data/is469/
        schedule.json   one entry per seminar: date, week, topic, key concepts, discussion prompts,
                        and "materials": filename patterns such as "*Topic7*" for that week's files
    materials folder (MATERIALS_DIR, git-ignored when the files are licensed), e.g. data/raw/is469/
        the lecture files themselves. Put them in slides/, readings/ and labs/ subfolders, or all in
        one folder: .pptx and .pdf count as slides, .ipynb as labs, .md and .txt as readings.

Every chunk keeps its file and its slide, page or cell number, so the Judge and the Auditor can cite
exactly where a piece of evidence came from.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import asdict, dataclass
from datetime import date as Date
from pathlib import Path

SUPPORTED = {".pdf", ".pptx", ".ipynb", ".md", ".txt"}
KIND_BY_FOLDER = {"slides": "slides", "readings": "reading", "labs": "lab"}
KIND_BY_SUFFIX = {".pptx": "slides", ".pdf": "slides", ".ipynb": "lab", ".md": "reading"}
PAGE_WORD = {"slides": "slide", "reading": "p.", "lab": "cell"}
_WEEK = re.compile(r"(?:week|topic)[\s_-]*(\d{1,2})", re.IGNORECASE)
_PAGE_HEADING = re.compile(r"^#{1,4}\s*(?:slide|page)\s+(\d+)\b.*$", re.IGNORECASE | re.MULTILINE)
_COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")  # "Topic7_Agentic_IS469 (1)" -> "Topic7_Agentic_IS469"


@dataclass
class Chunk:
    id: str
    text: str
    kind: str  # "slides", "reading" or "lab"
    doc: str  # path relative to the materials folder, e.g. "Topic7_Agentic_IS469.pptx"
    title: str
    week: int | None = None
    page: int | None = None  # slide number for decks, page for readings, first cell for labs

    def source(self) -> str:
        """Human-readable citation, e.g. "Topic7 Agentic IS469 (slides), slide 13"."""
        label = f"{self.title} ({self.kind})"
        if self.page is not None:
            label += f", {PAGE_WORD.get(self.kind, 'p.')} {self.page}"
        return label

    def context_text(self) -> str:
        """The chunk with its source in front, so a chunk cut from its document keeps its
        context (a cheap form of contextual RAG, Topic 8). This is what gets embedded and
        keyword-indexed."""
        week = f", week {self.week}" if self.week is not None else ""
        return f"[{self.source()}{week}] {self.text}"

    def to_dict(self) -> dict:
        return asdict(self)


# ---- schedule and lesson context ---------------------------------------------------------------


def load_schedule(course_dir: str | Path) -> dict:
    path = Path(course_dir) / "schedule.json"
    if not path.is_file():
        raise FileNotFoundError(f"No schedule.json in {course_dir}")
    return json.loads(path.read_text(encoding="utf-8"))


def lesson_for_date(schedule: dict, on: str | Date) -> dict | None:
    """The seminar held on `on`, or failing that the most recent one in the 6 days before it."""
    day = Date.fromisoformat(on) if isinstance(on, str) else on
    best = None
    for week in schedule.get("weeks", []):
        held = Date.fromisoformat(week["date"])
        if 0 <= (day - held).days <= 6 and (
            best is None or held > Date.fromisoformat(best["date"])
        ):
            best = week
    if best is None:
        return None
    return {
        "course_id": schedule.get("course_id"),
        "course_title": schedule.get("course_title"),
        **best,
    }


def matches(doc: str, patterns: list[str]) -> bool:
    """Whether a file matches any filename pattern, case-insensitively ("*Topic7*")."""
    name = doc.lower()
    return any(fnmatch.fnmatch(name, p.lower()) for p in patterns)


def week_materials(schedule: dict | None, week: int) -> list[str]:
    for entry in (schedule or {}).get("weeks", []):
        if int(entry["week"]) == week:
            return list(entry.get("materials", []))
    return []


def _week_of(relative: str, schedule: dict | None) -> int | None:
    """The first week whose materials patterns match the file, else a week or topic number in its
    name ("week03", "Topic7")."""
    for entry in (schedule or {}).get("weeks", []):
        if matches(relative, entry.get("materials", [])):
            return int(entry["week"])
    match = _WEEK.search(relative)
    return int(match.group(1)) if match else None


# ---- reading files -----------------------------------------------------------------------------


def split_into_chunks(text: str, window: int, overlap: int) -> list[str]:
    """Overlapping word windows, as in the Topic 8 lab."""
    words = text.split()
    if not words:
        return []
    step = max(1, window - overlap)
    chunks = []
    for start in range(0, len(words), step):
        chunks.append(" ".join(words[start : start + window]))
        if start + window >= len(words):
            break
    return chunks


def _markdown_pages(text: str) -> list[tuple[int | None, str]]:
    found = list(_PAGE_HEADING.finditer(text))
    if not found:
        return [(None, text)]
    pages = []
    preamble = text[: found[0].start()].strip().lstrip("#").strip()  # usually just the title
    if preamble:
        pages.append((None, preamble))
    for i, match in enumerate(found):
        end = found[i + 1].start() if i + 1 < len(found) else len(text)
        # The "## Slide 3" marker gives the number; it is not part of the slide's text.
        pages.append((int(match.group(1)), text[match.end() : end].strip()))
    return pages


def _notebook_pages(path: Path, min_words: int = 60) -> list[tuple[int | None, str]]:
    """Markdown and code cells (not outputs), with short neighbouring cells merged so a chunk has
    enough context. The page number is the first cell in each group, counting from 1."""
    cells = json.loads(path.read_text(encoding="utf-8")).get("cells", [])
    pages: list[tuple[int | None, str]] = []
    start, parts = None, []
    for number, cell in enumerate(cells, 1):
        if cell.get("cell_type") not in ("markdown", "code"):
            continue
        source = cell.get("source", "")
        text = ("".join(source) if isinstance(source, list) else str(source)).strip()
        if not text:
            continue
        start = start or number
        parts.append(text)
        if sum(len(p.split()) for p in parts) >= min_words:
            pages.append((start, "\n\n".join(parts)))
            start, parts = None, []
    if parts:
        pages.append((start, "\n\n".join(parts)))
    return pages


def read_pages(path: Path) -> list[tuple[int | None, str]]:
    """(slide, page or cell number, text) for each slide, page or cell group of a file."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from pypdf import PdfReader

        return [(i, p.extract_text() or "") for i, p in enumerate(PdfReader(str(path)).pages, 1)]
    if suffix == ".pptx":
        from pptx import Presentation

        pages = []
        for i, slide in enumerate(Presentation(str(path)).slides, 1):
            parts = [shape.text_frame.text for shape in slide.shapes if shape.has_text_frame]
            if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None:
                parts.append(slide.notes_slide.notes_text_frame.text)
            pages.append((i, "\n".join(p for p in parts if p.strip())))
        return pages
    if suffix == ".ipynb":
        return _notebook_pages(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return _markdown_pages(text) if suffix == ".md" else [(None, text)]


def _kind(relative: Path) -> str:
    if len(relative.parts) > 1 and relative.parts[0].lower() in KIND_BY_FOLDER:
        return KIND_BY_FOLDER[relative.parts[0].lower()]
    return KIND_BY_SUFFIX.get(relative.suffix.lower(), "reading")


def load_materials(
    materials_dir: str | Path, schedule: dict | None = None, window: int = 120, overlap: int = 30
) -> list[Chunk]:
    root = Path(materials_dir)
    if not root.is_dir():
        raise FileNotFoundError(
            f"No course materials at {root}. Put the slides and labs there (see data/README.md)."
        )
    if schedule is None and (root / "schedule.json").is_file():
        schedule = load_schedule(root)
    chunks: list[Chunk] = []
    files = sorted(
        p
        for p in root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in SUPPORTED
        and not p.name.startswith(".")
        and p.stem.lower() != "readme"  # notes about the folder, not course material
    )
    for path in files:
        relative = path.relative_to(root)
        doc = relative.as_posix()
        kind = _kind(relative)
        title = re.sub(r"[_-]+", " ", _COPY_SUFFIX.sub("", path.stem)).strip()
        week = _week_of(doc, schedule)
        for page, text in read_pages(path):
            for n, piece in enumerate(split_into_chunks(text, window, overlap)):
                chunks.append(Chunk(f"{doc}#{page or 0}.{n}", piece, kind, doc, title, week, page))
    if not chunks:
        raise ValueError(f"No slides, readings or labs found under {root}")
    return chunks
