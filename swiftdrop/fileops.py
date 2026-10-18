"""Moving finished downloads into the destination folder safely."""

from __future__ import annotations

import contextlib
import os
import shutil
import threading
from pathlib import Path

from swiftdrop.filenames import _truncate_utf8, sanitize_filename, split_ext
from swiftdrop.logging_setup import get_logger

log = get_logger("fileops")
NAME_LIMIT_BYTES = 255  # APFS / HFS+ / exFAT file name limit
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


def _same_volume(a: Path, b: Path) -> bool:
    return a.stat().st_dev == b.stat().st_dev


def _copy_temp_path(target: Path) -> Path:
    """Hidden temp name next to ``target`` that never exceeds the 255-byte name limit."""
    suffix = ".sdcopy"
    stem = _truncate_utf8(target.name, NAME_LIMIT_BYTES - 1 - len(suffix))
    return target.with_name(f".{stem}{suffix}")


def move_into_place(source: Path, reserved_target: Path) -> Path:
    """Move ``source`` onto the placeholder created by :func:`reserve_unique_path`."""
    temp: Path | None = None
    try:
        if _same_volume(source, reserved_target.parent):
            os.replace(source, reserved_target)
        else:
            # Different volume: copy next to the target, then atomically swap it in.
            temp = _copy_temp_path(reserved_target)
            shutil.copy2(source, temp)
            os.replace(temp, reserved_target)
            temp = None
            source.unlink(missing_ok=True)
    except BaseException:
        if temp is not None:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)
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
