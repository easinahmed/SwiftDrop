"""The shared state of one segmented download: the byte-range map and its counters.

Split out of ``segmented.py``. ``_Job.lock`` guards the segment map, the connection counters,
the rescue bookkeeping and the peer rates; ``snapshot()`` is what gets persisted for resume.
"""

from __future__ import annotations

import collections
import statistics
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from requests.cookies import RequestsCookieJar

from swiftdrop.cancel import CancelToken

MAX_RESCUES_PER_MINUTE = 12
PEER_RATE_TTL = 30.0  # how long another connection's last measured rate counts as a reference


class _Halted(Exception):
    """The job stopped or another worker failed; this worker just exits."""


@dataclass(slots=True)
class _Segment:
    start: int
    end: int  # inclusive; shrinks when another worker takes over the tail
    written: int = 0
    owned: bool = False

    @property
    def pos(self) -> int:
        return self.start + self.written

    @property
    def remaining(self) -> int:
        return self.end - self.pos + 1


@dataclass(eq=False)
class _Job:
    """One download's shared state. ``lock`` guards the private segment map and the counters."""

    url: str
    seg_path: Path
    size: int
    headers: dict[str, str]
    cookies: RequestsCookieJar | None
    validator: str | None  # sent as If-Range
    check: tuple[str, str] | None  # (header, value) every response must repeat
    reject_html: bool
    token: CancelToken
    split_floor: int
    segments: list[_Segment]
    shed_403: bool = True  # a 403 after earlier success means throttling (else: an expired link)
    target: int = 1  # connections this job aims for; lowered when the server pushes back

    def __post_init__(self) -> None:
        self.lock = threading.Lock()
        self.halt = threading.Event()
        self.error: BaseException | None = None
        self.connections = 0
        self.ranged_ok = False  # some ranged request already succeeded
        self.rescues = 0
        self.rescue_times: collections.deque[float] = collections.deque()
        self.rates: dict[int, tuple[float, float]] = {}  # conn id -> (bytes/s, measured at)
        self.min_target = self.max_connections = self.target

    def ensure_running(self) -> None:
        if self.halt.is_set() or self.token.stopped:
            raise _Halted

    def fail(self, exc: BaseException) -> None:
        with self.lock:
            if self.error is None:
                self.error = exc
        self.halt.set()

    def _next(self) -> _Segment | None:
        free = next((s for s in self.segments if not s.owned and s.remaining > 0), None)
        if free is not None:
            return free
        splittable = [s for s in self.segments if s.remaining >= 2 * self.split_floor]
        return max(splittable, key=lambda s: s.remaining, default=None)

    def has_work(self) -> bool:
        with self.lock:
            return self._next() is not None

    def claim(self) -> _Segment | None:
        """An unowned range, else the unwritten second half of the largest range being fetched."""
        with self.lock:
            seg = self._next()
            if seg is None:
                return None
            if not seg.owned:
                seg.owned = True
                return seg
            # The owner may be writing one block (<= BLOCK <= split_floor) past its recorded
            # position, which stays below `mid`, so the halves never overlap.
            mid = seg.pos + seg.remaining // 2
            tail = _Segment(start=mid, end=seg.end, owned=True)
            seg.end = mid - 1
            self.segments.append(tail)
            return tail

    def snapshot(self) -> tuple[tuple[int, int, int], ...]:
        """The map as a new tuple of ``(start, end, written)``; consistent, never mutated afterwards."""
        with self.lock:
            return tuple((s.start, s.end, s.written) for s in sorted(self.segments, key=lambda s: s.start))

    def span(self, seg: _Segment) -> tuple[int, int]:
        with self.lock:
            return seg.pos, seg.end

    def writable(self, seg: _Segment, pos: int, length: int) -> int:
        with self.lock:
            return max(0, min(length, seg.end - pos + 1))

    def record(self, seg: _Segment, length: int) -> None:
        with self.lock:
            seg.written = min(seg.written + length, seg.end - seg.start + 1)

    def opened(self, delta: int) -> None:
        with self.lock:
            self.connections += delta
            self.max_connections = max(self.max_connections, self.connections)

    def shed(self) -> None:
        """The server pushed back (429/503/403 after success): aim for one connection fewer."""
        with self.lock:
            self.target = max(1, self.target - 1)
            self.min_target = min(self.min_target, self.target)

    def leave_if_excess(self) -> bool:
        """Atomically give up this worker's connection when there are more than the target."""
        with self.lock:
            if self.connections > self.target:
                self.connections -= 1
                return True
            return False

    def allow_rescue(self) -> bool:
        now = time.monotonic()
        with self.lock:
            while self.rescue_times and now - self.rescue_times[0] > 60.0:
                self.rescue_times.popleft()
            if len(self.rescue_times) >= MAX_RESCUES_PER_MINUTE:
                return False
            self.rescue_times.append(now)
            self.rescues += 1
            return True

    def publish_rate(self, conn: int, rate: float, now: float) -> float | None:
        """Record this connection's rate; return the median of the other recent ones (None if none)."""
        with self.lock:
            self.rates[conn] = (rate, now)
            peers = [r for c, (r, t) in self.rates.items() if c != conn and now - t <= PEER_RATE_TTL]
        return statistics.median(peers) if peers else None

    def forget_rate(self, conn: int) -> None:
        with self.lock:
            self.rates.pop(conn, None)

    def stats(self) -> tuple[int, int]:
        """(bytes written, open connections)."""
        with self.lock:
            return sum(s.written for s in self.segments), self.connections

    def complete(self) -> bool:
        with self.lock:
            spans = sorted((s.start, s.end, s.written) for s in self.segments)
        expected = 0
        for start, end, written in spans:
            if start != expected or written != end - start + 1:
                return False
            expected = end + 1
        return expected == self.size
