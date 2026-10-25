import os

import pytest

from client.engine import DEFAULT_BINARY
from experiments.synthetic_bidders import Summary, run

BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
pytestmark = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")


class FakeTime:
    """A clock whose sleep just advances it, so a 10 second run is instant."""

    def __init__(self):
        self.t = 100.0

    def clock(self):
        return self.t

    def sleep(self, seconds):
        self.t += max(seconds, 1e-9)  # never stall on a float rounding gap


def run_fake(**kw) -> Summary:
    ft = FakeTime()
    return run(clock=ft.clock, sleep=ft.sleep, out=lambda _: None, **kw)


def test_ten_second_run_matches_the_expected_market_shape():
    s = run_fake(duration=10, limit=30, bid_rate=1.0, seed=0)
    assert s.released == 5  # t = 0, 2, 4, 6, 8; the run ends before t = 10
    assert s.sold > 0 and s.bids_unfilled > 0  # demand beat supply, so bids queued
    assert s.sold_on_release > 0  # some slices found a queued bid at release


def test_idle_market_expires_every_slice():
    s = run_fake(duration=10, limit=30, bid_rate=0.001, seed=0)
    assert s.released == 5
    assert s.sold == 0
    assert s.expired == 4 and s.open_at_end == 1


def test_low_bids_arriving_late_take_resting_slices_at_the_reserve():
    s = run_fake(duration=20, limit=30, bid_rate=0.3, seed=3)
    assert s.sold_late > 0  # the pricing wrinkle: bids that took a resting slice
    assert s.sold == s.sold_on_release + s.sold_late
