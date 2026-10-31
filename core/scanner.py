from __future__ import annotations

import hashlib
import os
import threading
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True)
class FileRecord:
    path: Path
    size: int
    digest: str

    @property
    def name(self) -> str:
        return self.path.name

    @property
    def extension(self) -> str:
        return self.path.suffix.lower() or "(no extension)"


@dataclass
class ScanResult:
    root: Path
    files_scanned: int
    records: list[FileRecord]
    duplicate_groups: list[list[FileRecord]]
    errors: list[str]

    @property
    def extra_copies(self) -> int:
        return sum(len(group) - 1 for group in self.duplicate_groups)

    @property
    def savings_bytes(self) -> int:
        return sum((len(group) - 1) * group[0].size for group in self.duplicate_groups)


def _iter_files(root: Path, recursive: bool) -> tuple[list[Path], list[str]]:
    files: list[Path] = []
    errors: list[str] = []

    if recursive:
        def on_error(error: OSError) -> None:
            errors.append(f"{getattr(error, 'filename', root)}: {error}")

        for current, dirs, names in os.walk(root, followlinks=False, onerror=on_error):
            dirs[:] = [
                name for name in dirs
                if not (Path(current) / name).is_symlink()
            ]
            for name in names:
                path = Path(current) / name
                if not path.is_symlink() and path.is_file():
                    files.append(path)
    else:
        try:
            for path in root.iterdir():
                if not path.is_symlink() and path.is_file():
                    files.append(path)
        except OSError as error:
            errors.append(f"{root}: {error}")

    return files, errors


def scan_folder(
    folder: str | Path,
    recursive: bool,
    cancel_event: threading.Event,
    progress: Callable[[int, int, str], None] | None = None,
) -> ScanResult:
    root = Path(folder).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {root}")

    paths, errors = _iter_files(root, recursive)
    # Equal-sized files are the only possible duplicates. Avoid hashing files
    # that cannot belong to a duplicate group.
    by_size: dict[int, list[Path]] = defaultdict(list)
    for path in paths:
        try:
            by_size[path.stat(follow_symlinks=False).st_size].append(path)
        except OSError as error:
            errors.append(f"{path}: {error}")

    candidates = [path for group in by_size.values() if len(group) > 1 for path in group]
    records: list[FileRecord] = []
    processed = 0
    total = len(candidates)
    for path in candidates:
        if cancel_event.is_set():
            break
        try:
            before = path.stat(follow_symlinks=False)
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                while True:
                    if cancel_event.is_set():
                        break
                    chunk = stream.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    digest.update(chunk)
            if cancel_event.is_set():
                break
            after = path.stat(follow_symlinks=False)
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                errors.append(f"{path}: changed while being scanned; skipped")
            else:
                records.append(FileRecord(path=path, size=after.st_size, digest=digest.hexdigest()))
        except OSError as error:
            errors.append(f"{path}: {error}")
        processed += 1
        if progress is not None:
            progress(processed, total, str(path))

    grouped: dict[tuple[int, str], list[FileRecord]] = defaultdict(list)
    for record in records:
        grouped[(record.size, record.digest)].append(record)
    duplicate_groups = [
        sorted(group, key=lambda record: (str(record.path).casefold(), str(record.path)))
        for group in grouped.values()
        if len(group) > 1
    ]
    duplicate_groups.sort(key=lambda group: str(group[0].path).casefold())
    return ScanResult(
        root=root,
        files_scanned=len(paths),
        records=records,
        duplicate_groups=duplicate_groups,
        errors=errors,
    )
