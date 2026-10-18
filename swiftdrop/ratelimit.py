"""Global bandwidth limiting for direct downloads (token bucket)."""

from __future__ import annotations

import threading
import time

from swiftdrop.cancel import CancelToken


class TokenBucket:
    """Shared across all running direct downloads; ``rate == 0`` means unlimited."""

    def __init__(self, rate_bytes_per_sec: int = 0) -> None:
        self._lock = threading.Lock()
        self._rate = max(0, int(rate_bytes_per_sec))
        self._tokens = float(self._rate)
        self._updated = time.monotonic()

    @property
    def rate(self) -> int:
        return self._rate

    def set_rate(self, rate_bytes_per_sec: int) -> None:
        with self._lock:
            self._rate = max(0, int(rate_bytes_per_sec))
            self._tokens = min(self._tokens, float(self._rate))
            self._updated = time.monotonic()

    def consume(self, amount: int, token: CancelToken | None = None) -> None:
        """Block until ``amount`` bytes may be transferred (or the token stops)."""
        remaining = float(amount)
        while remaining > 0:
            with self._lock:
                rate = self._rate
                if rate <= 0:
                    return
                now = time.monotonic()
                self._tokens = min(float(rate), self._tokens + (now - self._updated) * rate)
                self._updated = now
                take = min(remaining, self._tokens)
                self._tokens -= take
                remaining -= take
                wait = 0.0 if remaining <= 0 else min(0.25, remaining / rate)
            if wait > 0:
                if token is not None:
                    if token.wait(wait):
                        return
                else:
                    time.sleep(wait)
