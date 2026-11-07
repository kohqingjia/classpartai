"""Download the server's test data (recordings, voices, the database) as one zip.

The audio lives only on the deployed server's volume (``CLASSPARTAI_DATA_DIR``), so a teammate
who wants to run the Listener or the evaluations on their own machine needs a way to get it.
This builds the zip; app.py's "Download data" page offers it behind ``EXPORT_PASSWORD``.

Nothing here is a secret store: recordings and the database hold students' voices and
assessments, which is why the page refuses to work unless a password is set on the server.
"""

import hmac
import sqlite3
import tempfile
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO


@dataclass(frozen=True)
class Group:
    key: str
    label: str
    note: str
    files: Callable[[], list[tuple[Path, str]]]  # (file on disk, path inside the zip)
    personal: bool = False  # voices or student records: handle with care


def _tree(folder: Path, inside: str, patterns: tuple[str, ...] = ("*",)) -> list[tuple[Path, str]]:
    found = []
    for pattern in patterns:
        found += [
            (p, f"{inside}/{p.relative_to(folder).as_posix()}") for p in folder.rglob(pattern)
        ]
    return sorted({(p, a) for p, a in found if p.is_file()}, key=lambda pair: pair[1])


def groups(data_dir: Path, enrollment_dir: Path, repo_root: Path) -> list[Group]:
    return [
        Group(
            "recordings",
            "Class recordings",
            "Audio saved with each class session (var/recordings).",
            lambda: _tree(data_dir / "recordings", "recordings"),
            personal=True,
        ),
        Group(
            "demo-seminars",
            "Demo seminars: audio and scripts",
            "The seven scripted demo seminars with their timed scripts (cloned voices).",
            lambda: _tree(data_dir / "demo-seminars", "demo-seminars"),
        ),
        Group(
            "voices",
            "Enrolled voice samples",
            "Each enrolled person's reference clip, as the speaker match uses it.",
            lambda: _tree(enrollment_dir, "enrollments"),
            personal=True,
        ),
        Group(
            "library",
            "Course library",
            "The uploaded slides and readings, split into passages (documents.json).",
            lambda: _tree(data_dir / "library", "library"),
        ),
        Group(
            "listener-eval",
            "Listener evaluation cache",
            "The cached model outputs eval/listener/compare.py scores from.",
            lambda: _tree(repo_root / "eval" / "listener", "eval-listener", ("*.json",)),
        ),
        Group(
            "results",
            "Evaluation results",
            "Every file in eval/results.",
            lambda: _tree(repo_root / "eval" / "results", "eval-results"),
        ),
        Group(
            "database",
            "Database snapshot (assessments.db)",
            "Sessions, transcripts, drafts, approvals and the usage ledger. Students' names.",
            lambda: [],  # added by build_archive from a consistent snapshot
            personal=True,
        ),
    ]


def allowed(password: str, configured: str) -> bool:
    """True only if a password is configured and matches (constant-time)."""
    return bool(configured) and hmac.compare_digest(password.encode(), configured.encode())


def snapshot(db: Path, target: Path) -> Path | None:
    """A consistent copy of the live SQLite file (safe while the app is writing to it)."""
    if not db.is_file():
        return None
    with sqlite3.connect(db) as source, sqlite3.connect(target) as copy:
        source.backup(copy)
    return target


def build_archive(selected: list[Group], data_dir: Path, out: BinaryIO) -> list[dict]:
    """Write the chosen groups into ``out`` as a zip; returns a row per group for the page."""
    rows = []
    with (
        tempfile.TemporaryDirectory() as tmp,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive,
    ):
        for group in selected:
            files = group.files()
            if group.key == "database":
                copy = snapshot(data_dir / "assessments.db", Path(tmp) / "assessments.db")
                files = [(copy, "assessments.db")] if copy else []
            size = 0
            for path, name in files:
                # Audio is already compressed; storing it avoids minutes of wasted CPU.
                kind = zipfile.ZIP_STORED if path.suffix.lower() in (".wav", ".mp3") else None
                archive.write(path, name, compress_type=kind)
                size += path.stat().st_size
            rows.append({"group": group.label, "files": len(files), "bytes": size})
    return rows
