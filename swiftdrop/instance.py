"""Single-instance guard: an exclusive, non-blocking lock on ``instance.lock``.

macOS uses ``flock``; Windows locks the file's first byte with ``msvcrt.locking``.
Either lock is released by the OS when the process exits.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path


def _lock(fd: int) -> None:
    """Raise OSError when another process holds the lock."""
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


class InstanceLock:
    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            _unlock(fd)
        finally:
            os.close(fd)

    def __del__(self) -> None:
        with contextlib.suppress(OSError):
            self.release()


def acquire_instance_lock(data_dir: Path) -> InstanceLock | None:
    """Take the lock, or return None when another process already holds it."""
    fd = os.open(data_dir / "instance.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _lock(fd)
    except OSError:
        os.close(fd)
        return None
    return InstanceLock(fd)
