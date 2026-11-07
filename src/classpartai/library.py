"""The course library: slides, readings and labs the professor uploads for the evidence agents.

Each file becomes one ``assessment.Document`` (a passage per slide, page or notebook cell group),
read with Research's file readers (research/bridge.documents_from_materials). New class sessions
copy the library's documents into their inputs, so a session keeps the exact documents its
evidence and scores refer to even if the library changes later.

Uploaded files are licensed course material: they live under DATA_DIR (the server's data volume,
git-ignored locally), never in the repository.
"""

import json
import re
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path

from classpartai.assessment import Document

SUPPORTED = (".pdf", ".pptx", ".ipynb", ".md", ".txt")
MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_DOCUMENTS = 100  # AssessmentInputs' limit


def safe_name(name: str) -> str:
    stem, suffix = Path(name).stem, Path(name).suffix.lower()
    stem = re.sub(r"[^A-Za-z0-9 ._()-]+", "_", stem).strip(" .") or "file"
    return stem[:120] + suffix


class Library:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.files = self.root / "files"
        self.index = self.root / "documents.json"
        self.lock = threading.Lock()

    def entries(self) -> list[dict]:
        """[{"file", "uploadedAt", "document"}], oldest first."""
        if not self.index.exists():
            return []
        return json.loads(self.index.read_text(encoding="utf-8"))

    def documents(self) -> list[dict]:
        return [e["document"] for e in self.entries()]

    def _save(self, entries: list[dict]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.index.with_suffix(".tmp")
        tmp.write_text(json.dumps(entries))
        tmp.replace(self.index)

    def add(self, filename: str, data: bytes) -> dict:
        """Read one uploaded file into a document; a file with the same name is replaced."""
        from classpartai.research.bridge import documents_from_materials

        name = safe_name(filename)
        if Path(name).suffix not in SUPPORTED:
            raise ValueError(f"{filename}: supported types are {', '.join(SUPPORTED)}")
        if len(data) > MAX_FILE_BYTES:
            raise ValueError(f"{filename}: files must be 50 MB or smaller")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / name).write_bytes(data)
            try:
                found = documents_from_materials(tmp)
            except ValueError:
                found = []
        if not found:
            raise ValueError(f"{filename}: no readable text found")
        document = found[0]
        document["source"] = f"Course library: {name}"[:200]
        with self.lock:
            entries = [e for e in self.entries() if e["file"] != name]
            if len(entries) >= MAX_DOCUMENTS:
                raise ValueError(f"The library holds at most {MAX_DOCUMENTS} files")
            taken = {e["document"]["id"] for e in entries}
            base, n = document["id"][:76], 2
            while document["id"] in taken:
                document["id"], n = f"{base}-{n}", n + 1
            Document.model_validate(document)
            self.files.mkdir(parents=True, exist_ok=True)
            (self.files / name).write_bytes(data)
            entries.append(
                {
                    "file": name,
                    "uploadedAt": datetime.now(UTC).isoformat(timespec="seconds"),
                    "document": document,
                }
            )
            self._save(entries)
        return document

    def remove(self, filename: str) -> None:
        with self.lock:
            self._save([e for e in self.entries() if e["file"] != filename])
            (self.files / filename).unlink(missing_ok=True)
