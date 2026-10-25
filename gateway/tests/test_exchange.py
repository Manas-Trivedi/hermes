import os

import pytest

from client import Engine
from client.engine import DEFAULT_BINARY
from experiments.tests.helpers import real_sender
from gateway import ExchangeCore, ExchangeGateway, Task

BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
pytestmark = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")


def test_bid_waiting_when_a_slice_is_released_wins_at_its_own_price():
    with Engine(arena=100) as engine:
        core = ExchangeCore(engine, limit_per_minute=10, start=106.0)  # slices every 6s
        bid = Task("a", 50)
        assert core.submit(bid) == []  # no slice yet, so the bid rests
        [fill] = core.tick(106.0)
        assert fill.task is bid and fill.paid == 50


def test_bid_placed_while_a_slice_is_resting_wins_at_once_and_pays_only_the_reserve():
    with Engine(arena=100) as engine:
        core = ExchangeCore(engine, limit_per_minute=10, start=100.0)
        assert core.tick(100.0) == []  # a slice is released and rests unsold
        [fill] = core.submit(Task("a", 50))
        assert fill.paid == 1


def test_highest_bid_wins_each_slice_and_the_losers_stay_in_the_book():
    with Engine(arena=100) as engine:
        core = ExchangeCore(engine, limit_per_minute=10, start=106.0)
        for name, bid in [("lo", 10), ("hi", 50), ("mid", 30)]:
            core.submit(Task(name, bid))
        winners = [core.tick(t)[0].task.request_id for t in (106.0, 112.0, 118.0)]
        assert winners == ["hi", "mid", "lo"]
        assert core.tick(124.0) == []  # nothing left to sell to


def test_bid_below_the_reserve_is_rejected_instead_of_resting_forever():
    with Engine(arena=100) as engine:
        core = ExchangeCore(engine, limit_per_minute=10, start=100.0, reserve_price=5)
        with pytest.raises(ValueError):
            core.submit(Task("a", 4))


def run_gateway(gateway_limit, backend_limit, bids, tolerance=0.02):
    """Real engine, scheduler, mock backend and threads. The first bid takes the
    slice that is resting at start; the rest queue behind it and are ordered."""
    events = []
    with Engine(arena=1000) as engine, real_sender(backend_limit, tolerance) as sender:
        with ExchangeGateway(sender, engine, gateway_limit, on_event=events.append) as gw:
            first = gw.submit(*bids[0])
            assert first.wait(10)
            tasks = [first] + [gw.submit(*b) for b in bids[1:]]
            assert all(t.wait(10) for t in tasks)
    return tasks, gw, events


def test_calls_are_forwarded_in_bid_order_after_they_win_and_pay_what_the_book_says():
    tasks, gw, events = run_gateway(600, 600, [("first", 5), ("lo", 10), ("hi", 50), ("mid", 30)], tolerance=0.05)
    assert [t.status for t in tasks] == [200] * 4 and gw.wasted_retries == 0
    sent = [e["request_id"] for e in events if e["event"] == "forward"]
    assert sent == ["first", "hi", "mid", "lo"]
    # tasks are in submission order: "first" was late and pays only the reserve
    assert [t.paid for t in tasks] == [1, 10, 50, 30]
    for e in events:  # a call never leaves before its own fill
        if e["event"] == "forward":
            fill = next(f for f in events if f["event"] == "fill" and f["request_id"] == e["request_id"])
            assert fill["t"] <= e["t"]


def test_call_the_backend_rejects_after_winning_is_bid_again_and_counted():
    # Slices come every 0.1s but the backend accepts one per 0.2s.
    tasks, gw, _ = run_gateway(600, 300, [("a", 10), ("b", 10), ("c", 10)])
    assert [t.status for t in tasks] == [200] * 3
    assert gw.wasted_retries >= 1
    assert sum(t.attempts for t in tasks) == 3 + gw.wasted_retries


def test_cancelled_bid_leaves_the_book_and_cancelling_after_a_fill_is_a_no_op():
    with Engine(arena=100) as engine:
        core = ExchangeCore(engine, limit_per_minute=10, start=106.0)
        gone, won = Task("gone", 10), Task("won", 50)
        core.submit(gone)
        core.submit(won)
        assert core.cancel(gone) is True and core.cancel(gone) is False
        [fill] = core.tick(106.0)
        assert fill.task is won  # the cancelled bid is not there to be hit
        assert core.cancel(won) is False  # it already won, so its call goes out
        assert core.tick(112.0) == []


def test_cancelled_task_is_never_sent_and_its_waiter_wakes():
    events = []
    with Engine(arena=1000) as engine, real_sender(600) as sender:
        with ExchangeGateway(sender, engine, 600, on_event=events.append) as gw:
            first = gw.submit("first", 5)  # takes the slice resting at start
            assert first.wait(10)
            dropped, kept = gw.submit("dropped", 10), gw.submit("kept", 20)
            assert gw.cancel(dropped) is True
            assert dropped.wait(1) and dropped.cancelled and dropped.status is None
            assert kept.wait(10) and kept.status == 200
    sent = [e["request_id"] for e in events if e["event"] == "forward"]
    assert sent == ["first", "kept"]
