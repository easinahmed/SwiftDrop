"""Progress reporting primitives and an honest speed / ETA estimator."""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class ProgressUpdate:
    downloaded: int | None = None
    total: int | None = None
    total_is_estimate: bool = False
    speed: float | None = None
    eta: float | None = None
    progress: float | None = None
    phase: str | None = None
    processing: bool = False  # post-processing (merge / convert / move) rather than transferring


class SpeedMeter:
    """Measures throughput over a sliding window of real byte counts.

    Speed is reported only after enough data was observed, and ETA only when
    the total size is known, so the UI never shows invented numbers.
    """

    def __init__(
        self, window: float = 4.0, min_elapsed: float = 0.75, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._window = window
        self._min_elapsed = min_elapsed
        self._clock = clock
        self._samples: deque[tuple[float, int]] = deque()
        self._smoothed: float | None = None

    def reset(self) -> None:
        self._samples.clear()
        self._smoothed = None

    def update(self, downloaded: int) -> float | None:
        now = self._clock()
        self._samples.append((now, downloaded))
        while len(self._samples) > 2 and now - self._samples[0][0] > self._window:
            self._samples.popleft()
        first_t, first_b = self._samples[0]
        elapsed = now - first_t
        if elapsed < self._min_elapsed:
            return self._smoothed
        instant = max(0.0, (downloaded - first_b) / elapsed)
        self._smoothed = instant if self._smoothed is None else 0.7 * self._smoothed + 0.3 * instant
        return self._smoothed

    @property
    def speed(self) -> float | None:
        return self._smoothed

    def eta(self, downloaded: int, total: int | None) -> float | None:
        if not total or not self._smoothed or self._smoothed < 1:
            return None
        remaining = max(0, total - downloaded)
        return remaining / self._smoothed


class Throttle:
    """Lets at most one event through per ``interval`` seconds (plus forced ones)."""

    def __init__(self, interval: float = 0.25, clock: Callable[[], float] = time.monotonic) -> None:
        self._interval = interval
        self._clock = clock
        self._last = 0.0

    def ready(self, force: bool = False) -> bool:
        now = self._clock()
        if force or now - self._last >= self._interval:
            self._last = now
            return True
        return False
