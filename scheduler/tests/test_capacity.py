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


def test_tokens_charged_to_the_scheduler_hold_back_the_next_slice_until_repaid(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0, tokens_per_minute=600)  # 10 tokens a second; a slice every 2s otherwise
    assert len(sched.tick(0).released) == 1
    sched.charge(50, now=0)  # repaid at 5s
    assert sched.tick(2).released == [] and sched.tick(4.9).released == []
    assert sched.next_deadline() == 5
    assert len(sched.tick(5).released) == 1
    assert sched.tick(5.5).released == []  # back on the 2s grid: the slots missed while blocked were skipped, not saved up
    assert len(sched.tick(6).released) == 1


def test_tokens_owed_add_up_but_idle_time_is_not_banked(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0, tokens_per_minute=600)
    sched.charge(30, now=0)
    sched.charge(30, now=1)  # still owing the first: repaid at 3 + 3 = 6s
    assert sched.next_deadline() == 6
    sched.charge(10, now=100)  # long idle: it starts from now, not from the debt that was cleared long ago
    assert sched.next_deadline() == 101


def test_the_request_limit_still_holds_when_tokens_are_small(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0, tokens_per_minute=600)
    sched.tick(0)
    sched.charge(1, now=0)  # repaid at 0.1s, long before the 2s slot
    assert sched.tick(1).released == [] and len(sched.tick(2).released) == 1


def test_a_non_positive_token_limit_is_rejected(engine):
    with pytest.raises(ValueError):
        CapacityScheduler(engine, LIMIT, start=0, tokens_per_minute=0)


def adaptive(engine, **kw):
    return CapacityScheduler(engine, LIMIT, start=0, adaptive=True, **kw)  # a slice every 2s


def test_a_429_halves_the_rate_and_pushes_the_next_slice_out_by_the_longer_interval(engine):
    sched = adaptive(engine)
    sched.tick(0)
    sched.rejected(now=1.0)
    assert sched.scale == 0.5 and sched.interval == 4.0
    assert sched.tick(4.9).released == [] and len(sched.tick(5.0).released) == 1  # 1.0 + 4.0


def test_the_several_429s_of_one_burst_cut_once_and_a_later_429_cuts_again(engine):
    sched = adaptive(engine)
    for _ in range(3):
        sched.rejected(now=10.0)
    assert sched.scale == 0.5
    sched.rejected(now=14.0)  # a whole new interval later
    assert sched.scale == 0.25


def test_retry_after_holds_releases_even_when_the_rate_is_already_cut(engine):
    sched = adaptive(engine)
    sched.rejected(now=0.0, retry_after=30.0)
    sched.rejected(now=0.5, retry_after=5.0)  # a shorter one does not shorten the hold
    assert sched.next_deadline() == 30.0


def test_successes_climb_back_a_little_at_a_time_never_past_the_configured_rate_and_the_floor_holds(engine):
    sched = adaptive(engine)
    for i in range(10):
        sched.rejected(now=100.0 * i)
    assert sched.scale == 0.1
    for _ in range(10):
        sched.succeeded()
    assert sched.scale == pytest.approx(0.3)
    for _ in range(100):
        sched.succeeded()
    assert sched.scale == 1.0


def test_without_adaptive_nothing_moves(engine):
    sched = CapacityScheduler(engine, LIMIT, start=0)
    sched.rejected(now=1.0, retry_after=60.0)
    sched.succeeded()
    assert sched.scale == 1.0 and sched.next_deadline() == 0


def test_the_token_rate_slows_with_the_request_rate(engine):
    sched = adaptive(engine, tokens_per_minute=600)  # 10 tokens a second
    sched.rejected(now=0.0)  # half: 5 tokens a second
    sched.charge(50, now=10.0)
    assert sched.next_deadline() == 20.0
