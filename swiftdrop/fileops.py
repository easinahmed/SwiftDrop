"""Moving finished downloads into the destination folder safely."""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path

from swiftdrop.filenames import sanitize_filename, split_ext
from swiftdrop.logging_setup import get_logger

log = get_logger("fileops")
_reserve_lock = threading.Lock()


def reserve_unique_path(directory: Path, filename: str) -> Path:
    """Atomically claim ``directory/filename`` (or ``name (n).ext``).

    An empty placeholder is created with ``O_EXCL`` so concurrent jobs that
    finish with the same name can never overwrite each other or an existing
    file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    filename = sanitize_filename(filename)
    stem, ext = split_ext(filename)
    suffix = f".{ext}" if ext else ""
    with _reserve_lock:
        for counter in range(0, 10_000):
            name = filename if counter == 0 else f"{stem} ({counter}){suffix}"
            candidate = directory / name
            try:
                fd = os.open(candidate, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                continue
            os.close(fd)
            return candidate
    raise FileExistsError(f"No free filename for {filename} in {directory}")


def move_into_place(source: Path, reserved_target: Path) -> Path:
    """Move ``source`` onto the placeholder created by :func:`reserve_unique_path`."""
    try:
        if source.stat().st_dev == reserved_target.parent.stat().st_dev:
            os.replace(source, reserved_target)
        else:
            # Different volume: copy next to the target, then atomically swap it in.
            temp = reserved_target.with_name(f".{reserved_target.name}.swiftdrop-copy")
            shutil.copy2(source, temp)
            os.replace(temp, reserved_target)
            source.unlink(missing_ok=True)
    except BaseException:
        try:
            if reserved_target.exists() and reserved_target.stat().st_size == 0:
                reserved_target.unlink()
        except OSError:
            pass
        raise
    return reserved_target


def remove_tree(path: Path) -> int:
    """Delete a staging directory, returning the number of bytes freed."""
    if not path.exists():
        return 0
    freed = dir_size(path)
    shutil.rmtree(path, ignore_errors=True)
    return freed


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total
