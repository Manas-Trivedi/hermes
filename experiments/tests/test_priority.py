import time

from experiments.baselines import Gateway, PriorityDispatcher, Task
from experiments.tests.helpers import real_sender


def drain(d, start=0.0):
    """Pop every task in order, advancing time just enough for each send to be allowed."""
    order, now = [], start
    while len(d):
        order.append(d.pop_due(now).request_id)
        now += d.interval
    return order


def test_more_urgent_goes_first_and_equal_priority_keeps_arrival_order():
    d = PriorityDispatcher(limit_per_minute=10)
    for name, p in [("low", 1), ("hi1", 9), ("mid", 5), ("hi2", 9)]:
        d.submit(Task(name, p), 0.0)
    assert drain(d) == ["hi1", "hi2", "mid", "low"]


def test_aging_lets_old_low_priority_work_overtake_newer_urgent_work():
    def order(aging_rate):
        d = PriorityDispatcher(limit_per_minute=10, aging_rate=aging_rate)
        d.submit(Task("old-low", 0), 0.0)
        d.submit(Task("new-high", 5), 10.0)  # 10s later, 5 points more urgent
        return drain(d, start=10.0)

    assert order(aging_rate=0.0) == ["new-high", "old-low"]  # no aging: urgency wins
    assert order(aging_rate=1.0) == ["old-low", "new-high"]  # 10s waited = 10 points > 5


def test_rejected_task_is_retried_ahead_of_everything_that_arrived_since():
    d = PriorityDispatcher(limit_per_minute=10, aging_rate=1.0)
    first, later = Task("first", 5), Task("later", 5)
    d.submit(first, 0.0)
    assert d.pop_due(0.0) is first
    d.submit(later, 1.0)  # same priority, arrived after "first"
    d.retry(first, now=1.0, retry_after=0.0)
    assert d.pop_due(6.0) is first


def test_cancel_removes_a_queued_task_and_keeps_priority_order_of_the_rest():
    d = PriorityDispatcher(limit_per_minute=10)
    low, top, mid = Task("low", 1), Task("top", 9), Task("mid", 5)
    for t in (low, top, mid):
        d.submit(t, 0.0)
    assert d.cancel(top) is True and d.cancel(top) is False
    assert drain(d) == ["mid", "low"]


def test_gateway_cancel_keeps_a_queued_task_from_ever_being_sent():
    events = []
    with real_sender(backend_limit=600) as sender:
        with Gateway(sender, PriorityDispatcher(600), on_event=events.append) as gw:
            blocker = gw.submit("blocker", 0)
            while not any(e["event"] == "forward" for e in events):
                time.sleep(0.001)
            dropped, kept = gw.submit("dropped", 9), gw.submit("kept", 1)
            assert gw.cancel(dropped) is True
            assert dropped.wait(1) and dropped.cancelled
            assert blocker.wait(10) and kept.wait(10)
    sent = [e["request_id"] for e in events if e["event"] == "forward"]
    assert sent == ["blocker", "kept"]


def test_gateway_forwards_by_priority_not_arrival():
    events = []
    with real_sender(backend_limit=600) as sender:
        with Gateway(sender, PriorityDispatcher(600), on_event=events.append) as gw:
            # "blocker" takes the first send slot; the rest queue behind it and are ordered.
            tasks = [gw.submit("blocker", 0)]
            while not any(e["event"] == "forward" for e in events):
                time.sleep(0.001)
            tasks += [gw.submit(n, p) for n, p in [("lo", 1), ("hi", 9), ("mid", 5)]]
            assert all(t.wait(10) for t in tasks)
    # A jitter 429 makes a task forward twice but keeps its place, so compare
    # the order in which each task was first sent.
    first_sends = list(dict.fromkeys(e["request_id"] for e in events if e["event"] == "forward"))
    assert first_sends == ["blocker", "hi", "mid", "lo"]
