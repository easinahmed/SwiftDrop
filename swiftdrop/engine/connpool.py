"""A cap on open data connections shared by segmented downloads."""

from __future__ import annotations

import threading
import time

from swiftdrop.cancel import CancelToken

_POLL = 0.1  # how often a waiting acquire() re-checks its CancelToken


class ConnectionPool:
    """Counting semaphore whose waits give up when the job's token stops."""

    def __init__(self, limit: int = 32) -> None:
        self._limit = max(1, int(limit))
        self._in_use = 0
        self._cond = threading.Condition()

    @property
    def limit(self) -> int:
        return self._limit

    @property
    def in_use(self) -> int:
        with self._cond:
            return self._in_use

    def acquire(self, token: CancelToken, timeout: float | None = None) -> bool:
        """Take one connection slot. False if ``token`` stopped or ``timeout`` elapsed first."""
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._cond:
            while True:
                if token.stopped:
                    return False
                if self._in_use < self._limit:
                    self._in_use += 1
                    return True
                wait = _POLL if deadline is None else min(_POLL, deadline - time.monotonic())
                if wait <= 0:
                    return False
                self._cond.wait(wait)

    def release(self) -> None:
        with self._cond:
            if self._in_use <= 0:
                raise ValueError("ConnectionPool released more times than acquired")
            self._in_use -= 1
            self._cond.notify()


# The app-wide cap on open data connections (Settings has no say: it protects the network stack).
GLOBAL_POOL = ConnectionPool(32)
