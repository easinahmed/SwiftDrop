"""Single-instance guard: an exclusive, non-blocking flock on ``instance.lock``."""

from __future__ import annotations

import contextlib
import fcntl
import os
from pathlib import Path


class InstanceLock:
    def __init__(self, fd: int) -> None:
        self._fd: int | None = fd

    def release(self) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)

    def __del__(self) -> None:
        with contextlib.suppress(OSError):
            self.release()


def acquire_instance_lock(data_dir: Path) -> InstanceLock | None:
    """Take the lock, or return None when another process already holds it."""
    fd = os.open(data_dir / "instance.lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return InstanceLock(fd)
