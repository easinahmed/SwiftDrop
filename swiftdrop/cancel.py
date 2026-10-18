"""Cooperative cancellation shared between the queue and download engines."""

from __future__ import annotations

import threading
from enum import StrEnum


class StopReason(StrEnum):
    PAUSE = "pause"
    CANCEL = "cancel"
    SHUTDOWN = "shutdown"


class JobStopped(Exception):
    """Raised inside an engine when its job was paused, cancelled or the app quits."""

    def __init__(self, reason: StopReason) -> None:
        super().__init__(reason.value)
        self.reason = reason


class CancelToken:
    def __init__(self) -> None:
        self._event = threading.Event()
        self._reason: StopReason | None = None
        self._lock = threading.Lock()

    def stop(self, reason: StopReason) -> None:
        with self._lock:
            # A cancel request upgrades an earlier pause, never the other way around.
            if self._reason is None or reason == StopReason.CANCEL:
                self._reason = reason
        self._event.set()

    @property
    def stopped(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> StopReason | None:
        return self._reason

    def raise_if_stopped(self) -> None:
        if self._event.is_set():
            raise JobStopped(self._reason or StopReason.CANCEL)

    def wait(self, timeout: float) -> bool:
        """Sleep up to ``timeout`` seconds; returns True as soon as the token stops."""
        return self._event.wait(max(0.0, timeout))
