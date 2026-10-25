import os

import pytest

from client import Engine
from client.engine import DEFAULT_BINARY
from scheduler import SLICE_ID_BASE, CapacityScheduler

BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
pytestmark = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")

LIMIT = 30  # per minute, so one slice every 2 seconds


@pytest.fixture
def engine():
    with Engine(arena=50) as e:
        yield e


def slice_ids(engine):
    return [b.id for b in engine.book() if b.side == "ASK"]


def test_one_slice_per_interval_and_none_early(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0)
    released_at = []
    for step in range(0, 21):  # 0.0 .. 10.0 in half-second ticks
        now = step / 2
        if sched.tick(now).released:
            released_at.append(now)
    assert released_at == [0, 2, 4, 6, 8, 10]


def test_late_tick_skips_missed_slices_instead_of_bursting(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0)
    sched.tick(0)
    assert len(sched.tick(9).released) == 1  # 3 releases were missed, only one fires
    assert sched.tick(9.5).released == []
    assert len(sched.tick(10).released) == 1  # back on the original grid


def test_unsold_slice_is_cancelled_when_replaced(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0)
    first = sched.tick(0).released
    assert slice_ids(engine) == first
    result = sched.tick(2)
    assert result.expired == first
    assert slice_ids(engine) == result.released  # old one gone, new one resting


def test_expiry_tolerates_a_slice_sold_after_release(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0)
    sched.tick(0)
    assert len(engine.buy(1, 50, 1)) == 1  # a late bid takes the resting slice
    result = sched.tick(2)  # must not raise UnknownId
    assert result.expired == []


def test_slice_hits_highest_bid_at_that_bids_price(engine):
    engine.buy(5, 10, 1)
    engine.buy(7, 30, 1)
    engine.buy(6, 20, 1)
    sched = CapacityScheduler(engine, LIMIT, start=0)
    result = sched.tick(0)
    [trade] = result.trades
    assert (trade.taker_id, trade.maker_id, trade.price) == (SLICE_ID_BASE, 7, 30)
    assert [b.id for b in engine.book()] == [6, 5]
    assert slice_ids(engine) == []  # sold on release, nothing left to expire


def test_slice_ids_start_at_base_and_increase(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0)
    assert sched.tick(0).released == [SLICE_ID_BASE]
    assert sched.tick(2).released == [SLICE_ID_BASE + 1]


def test_burst_carries_unsold_capacity_over(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0, burst=3)
    for now in (0, 2, 4):
        sched.tick(now)
    assert slice_ids(engine) == [SLICE_ID_BASE + i for i in range(3)]
    result = sched.tick(6)  # first slice has now lived 3 intervals
    assert result.expired == [SLICE_ID_BASE]
    assert slice_ids(engine) == [SLICE_ID_BASE + i for i in (1, 2, 3)]
