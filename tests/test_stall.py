import pytest

from swiftdrop.engine.stall import StallDetector


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        (dict(idle_for=8.1, rate=1e6, peer_median=None, own_avg_30s=None), True),
        (dict(idle_for=1, rate=100_000, peer_median=3_000_000, own_avg_30s=None), True),
        (dict(idle_for=1, rate=300_000, peer_median=350_000, own_avg_30s=None), False),  # slow but steady
        (dict(idle_for=1, rate=100_000, peer_median=None, own_avg_30s=None), False),  # no reference
        (dict(idle_for=1, rate=400_000, peer_median=None, own_avg_30s=4_000_000), True),
        (dict(idle_for=1, rate=600_000, peer_median=9_000_000, own_avg_30s=None), False),  # above the floor
    ],
)
def test_detector_rules(kwargs, expected):
    assert StallDetector().should_rescue(**kwargs) is expected
