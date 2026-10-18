"""When is a connection stalled enough to be replaced?"""

from __future__ import annotations


class StallDetector:
    """Decides if a connection should be rescued (closed and reopened on a fresh socket).

    Rescue when it delivered nothing for ``idle`` seconds, or when its rate over the last
    ``window`` seconds is below ``floor`` bytes/s AND below ``ratio`` of the reference rate:
    the median of the other connections, else its own 30 s average. Without a reference only
    the idle rule applies, so a slow but steady server is never churned.
    """

    def __init__(self, *, idle: float = 8.0, window: float = 4.0, floor: float = 500_000, ratio: float = 0.25) -> None:
        self.idle = idle
        self.window = window
        self.floor = floor
        self.ratio = ratio

    def should_rescue(
        self,
        *,
        idle_for: float,
        rate: float,
        peer_median: float | None,
        own_avg_30s: float | None,
    ) -> bool:
        if idle_for >= self.idle:
            return True
        reference = peer_median if peer_median is not None else own_avg_30s
        return reference is not None and rate < self.floor and rate < self.ratio * reference
