import os
import time

import pytest

from client import Engine
from client.engine import DEFAULT_BINARY
from experiments.tests.helpers import real_sender
from pricing import AgentConfig, Budgets, TaskMeta
from gateway import ExchangeCore, ExchangeGateway, Task, check_lifecycle

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


def test_repriced_bid_competes_at_its_new_price_and_can_still_be_cancelled():
    with Engine(arena=100) as engine:
        core = ExchangeCore(engine, limit_per_minute=10, start=106.0)
        lo, hi = Task("lo", 10), Task("hi", 50)
        core.submit(lo)
        core.submit(hi)
        assert core.reprice(lo, 80) == [] and lo.bid == 80
        assert set(core.resting()) == {lo, hi}
        [fill] = core.tick(106.0)
        assert fill.task is lo and fill.paid == 80
        assert core.cancel(hi) is True  # the bid that was not repriced is still found
        with pytest.raises(ValueError):
            core.reprice(lo, 90)  # it already won, so it has no bid to replace


def test_aging_raises_waiting_bids_so_an_old_cheap_task_overtakes_but_never_lowers_one():
    events = []
    rescore = lambda task, now: {"old": 100, "mid": 5}.get(task.request_id, task.bid)
    with Engine(arena=1000) as engine, real_sender(300) as sender:
        with ExchangeGateway(sender, engine, 300, on_event=events.append, rescore=rescore, reprice_interval=0.02) as gw:
            first = gw.submit("first", 5)  # takes the slice resting at start
            assert first.wait(10)
            tasks = [gw.submit("mid", 30), gw.submit("old", 10)]  # slices come every 0.2s, aging every 0.02s
            assert all(t.wait(10) for t in tasks)
    assert [e["request_id"] for e in events if e["event"] == "forward"] == ["first", "old", "mid"]
    repriced = [(e["request_id"], e["previous"], e["offered"]) for e in events if e["event"] == "reprice"]
    assert repriced == [("old", 10, 100)]
    assert check_lifecycle(events) == []


def make_budgets():
    """Agents warm, rich and poor with starting balances 1000, 80 and 20 (rates 100, 8, 2 per second)."""
    agents = {"warm": AgentConfig(1, 100), "rich": AgentConfig(1, 8), "poor": AgentConfig(1, 2)}
    return Budgets(agents, pool=110.0, start=time.monotonic(), cap_seconds=10.0)


def test_bids_are_capped_at_the_balance_and_a_win_spends_what_was_paid():
    events = []
    budgets = make_budgets()
    with Engine(arena=1000) as engine, real_sender(300) as sender:
        with ExchangeGateway(sender, engine, 300, on_event=events.append, budgets=budgets) as gw:
            first = gw.submit("first", 5, TaskMeta("t", 0.0, agent_id="warm"))  # takes the slice resting at start
            assert first.wait(10)
            rich = gw.submit("rich", 1000, TaskMeta("t", 0.0, agent_id="rich"))
            poor = gw.submit("poor", 1000, TaskMeta("t", 0.0, agent_id="poor"))
            assert rich.wait(10) and poor.wait(10)
    offers = {e["request_id"]: (e["asked"], e["offered"]) for e in events if e["event"] == "bid"}
    assert offers["rich"] == (1000, 80) and offers["poor"] == (1000, 20)
    assert (rich.paid, poor.paid) == (80, 20)
    now = time.monotonic()
    assert budgets.balance("rich", now) < 10  # spent all 80, and only a moment of regeneration since
    assert budgets.balance("poor", now) < 10


def test_a_task_the_agent_cannot_afford_waits_unbid_until_credits_regenerate():
    events = []
    with Engine(arena=1000) as engine, real_sender(300) as sender:
        with ExchangeGateway(sender, engine, 300, on_event=events.append, budgets=make_budgets()) as gw:
            first = gw.submit("first", 5, TaskMeta("t", 0.0, agent_id="warm"))
            assert first.wait(10)
            drain = gw.submit("drain", 1000, TaskMeta("t", 0.0, agent_id="poor"))  # bids and pays all 20
            assert drain.wait(10) and drain.paid == 20
            broke = gw.submit("broke", 1000, TaskMeta("t", 0.0, agent_id="poor"))  # 2 credits a second
            assert broke.wait(10) and broke.status == 200
    when = {(e["request_id"], e["event"]): e["t"] for e in events}
    assert when["broke", "bid"] - when["broke", "request"] >= 0.3  # about half a second to earn the reserve
    assert check_lifecycle(events) == []


def test_a_task_waiting_for_credits_can_be_cancelled_and_is_never_bid():
    events = []
    with Engine(arena=1000) as engine, real_sender(300) as sender:
        with ExchangeGateway(sender, engine, 300, on_event=events.append, budgets=make_budgets()) as gw:
            first = gw.submit("first", 5, TaskMeta("t", 0.0, agent_id="warm"))
            assert first.wait(10)
            drain = gw.submit("drain", 1000, TaskMeta("t", 0.0, agent_id="poor"))
            assert drain.wait(10)
            broke = gw.submit("broke", 1000, TaskMeta("t", 0.0, agent_id="poor"))
            assert gw.cancel(broke) is True and broke.wait(1) and broke.cancelled
    assert not [e for e in events if e["request_id"] == "broke" and e["event"] in ("bid", "forward")]


def test_a_cancelled_bid_gives_its_credits_back_to_the_agent():
    budgets, events = make_budgets(), []
    with Engine(arena=1000) as engine, real_sender(300) as sender:
        with ExchangeGateway(sender, engine, 300, on_event=events.append, budgets=budgets) as gw:
            first = gw.submit("first", 5, TaskMeta("t", 0.0, agent_id="warm"))
            assert first.wait(10)
            big = gw.submit("big", 1000, TaskMeta("t", 0.0, agent_id="rich"))
            while not [e for e in events if e["request_id"] == "big" and e["event"] == "bid"]:
                time.sleep(0.001)  # resting in the book, holding its 80 credits
            assert budgets.available("other", "rich", time.monotonic()) < 5
            assert gw.cancel(big) is True
            assert budgets.available("other", "rich", time.monotonic()) >= 79


def test_aging_cannot_raise_a_bid_past_what_the_agent_can_afford():
    events = []
    budgets = make_budgets()
    rescore = lambda task, now: 1000
    with Engine(arena=1000) as engine, real_sender(300) as sender:
        with ExchangeGateway(sender, engine, 300, on_event=events.append, rescore=rescore,
                             reprice_interval=0.02, budgets=budgets) as gw:
            first = gw.submit("first", 5, TaskMeta("t", 0.0, agent_id="warm"))
            assert first.wait(10)
            rich = gw.submit("rich", 10, TaskMeta("t", 0.0, agent_id="rich"))
            assert rich.wait(10)
    repriced = [(e["previous"], e["offered"]) for e in events if e["event"] == "reprice" and e["request_id"] == "rich"]
    assert repriced == [(10, 80)]


def test_a_win_charges_its_tokens_and_the_next_slice_waits_for_them():
    with Engine(arena=100) as engine:
        core = ExchangeCore(engine, limit_per_minute=60, start=0.0, tokens_per_minute=600)  # a slice a second, 10 tokens a second
        for name in ("a", "b"):
            core.submit(Task(name, 10, tokens=50))
        fills = core.tick(0.0)
        core.charge(fills, 0.0)
        assert [f.task.request_id for f in fills] == ["a"]
        assert core.tick(1.0) == [] and core.tick(4.9) == []  # 50 tokens take 5 seconds to repay
        assert [f.task.request_id for f in core.tick(5.0)] == ["b"]


def test_through_the_gateway_calls_are_spaced_by_their_tokens_not_just_the_request_rate():
    events = []
    with Engine(arena=100) as engine, real_sender(600, 0.05) as sender:
        with ExchangeGateway(sender, engine, 600, on_event=events.append, tokens_per_minute=300) as gw:  # 5 tokens a second
            tasks = [gw.submit("first", 5, tokens=3)]
            assert tasks[0].wait(10)
            tasks += [gw.submit(f"t{i}", 5, tokens=3) for i in range(2)]
            assert all(t.wait(10) for t in tasks)
    sent = [e["t"] for e in events if e["event"] == "forward"]
    assert len(sent) == 3 and all(b - a >= 0.55 for a, b in zip(sent, sent[1:]))  # 3 tokens = 0.6s, against 0.1s from the request rate


def test_a_backend_stricter_than_the_configured_limit_is_found_instead_of_hammered():
    def waste(adaptive):
        with Engine(arena=1000) as engine, real_sender(120, 0.0) as sender:  # the backend really allows a call every 0.5s
            with ExchangeGateway(sender, engine, 600, adaptive=adaptive) as gw:  # configured for one every 0.1s
                tasks = [gw.submit(f"t{i}", 5) for i in range(8)]
                assert all(t.wait(30) for t in tasks)
            return gw.wasted_retries, [t.status for t in tasks], gw._core.rate_scale

    fixed, statuses, scale = waste(False)
    assert statuses == [200] * 8 and scale == 1.0
    learned, statuses, scale = waste(True)
    assert statuses == [200] * 8 and scale < 0.5
    assert learned < fixed / 2  # the point of adapting, with a wide margin
