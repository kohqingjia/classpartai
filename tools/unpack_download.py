"""Put the zip from the app's "Download data" page where the app and the evaluations look for it.

    uv run python tools/unpack_download.py classpartai-data.zip            # skips files you have
    uv run python tools/unpack_download.py classpartai-data.zip --force    # overwrites them
    uv run python tools/unpack_download.py classpartai-data.zip --dry-run  # only lists
    uv run python tools/unpack_download.py var/classpartai-data            # an already unzipped one

Every name in the zip maps to one place (``classpartai.exports.RESTORE``): recordings, demo
seminars, the course library, the class list and the database under the data folder (``var``),
voice samples under ``audio-service/enrollments``, evaluation caches and results under ``eval``.
Anything else in the zip is ignored, and nothing is written outside those places.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from classpartai.config import DATA_DIR  # noqa: E402
from classpartai.exports import RESTORE  # noqa: E402


def destination(name: str) -> Path | None:
    parts = PurePosixPath(name).parts
    if not parts or ".." in parts or PurePosixPath(name).is_absolute() or parts[0] not in RESTORE:
        return None
    base = RESTORE[parts[0]].replace("{data}", str(DATA_DIR))
    base = Path(base) if Path(base).is_absolute() else ROOT / base
    return base.joinpath(*parts[1:])


def entries(source: str):
    """(name inside the download, a function opening it) for a zip or an unzipped folder."""
    path = Path(source)
    if path.is_dir():
        for file in sorted(path.rglob("*")):
            if file.is_file():
                yield file.relative_to(path).as_posix(), lambda f=file: open(f, "rb")
        return
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            if not info.is_dir():
                yield info.filename, lambda i=info: archive.open(i)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", help="the zip, or the folder it was unzipped into")
    parser.add_argument("--force", action="store_true", help="overwrite files that already exist")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    counts: dict[str, list[int]] = {}
    for name, read in entries(args.zip):
        target = destination(name)
        top = PurePosixPath(name).parts[0]
        row = counts.setdefault(top, [0, 0, 0])  # written, skipped, ignored
        if target is None:
            row[2] += 1
        elif target.exists() and not args.force:
            row[1] += 1
        else:
            row[0] += 1
            if not args.dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                with read() as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)
    for top, (written, skipped, ignored) in sorted(counts.items()):
        where = RESTORE.get(top, "(not recognised)").replace("{data}", str(DATA_DIR))
        print(f"{top:16} -> {where}: {written} written, {skipped} kept, {ignored} ignored")
    if args.dry_run:
        print("Dry run: nothing was written.")


if __name__ == "__main__":
    main()
