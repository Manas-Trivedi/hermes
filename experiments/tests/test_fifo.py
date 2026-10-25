from experiments.baselines import FifoDispatcher, Gateway, Task
from experiments.tests.helpers import real_sender


def ids(*names):
    return [Task(n) for n in names]


def test_dispatcher_releases_in_arrival_order_one_per_interval():
    d = FifoDispatcher(limit_per_minute=10)  # one send per 6 seconds
    a, b, c = ids("a", "b", "c")
    for t in (a, b, c):
        d.submit(t, 0.0)
    assert d.pop_due(0.0) is a
    assert d.pop_due(0.0) is None and d.wake_in(0.0) == 6.0
    assert d.pop_due(5.9) is None
    assert d.pop_due(6.0) is b
    assert d.pop_due(12.0) is c
    assert d.wake_in(12.0) is None  # empty queue


def test_rejected_task_keeps_its_place_and_holds_all_sends_for_retry_after():
    d = FifoDispatcher(limit_per_minute=10)
    a, b = ids("a", "b")
    d.submit(a, 0.0)
    d.submit(b, 0.0)
    assert d.pop_due(0.0) is a
    d.retry(a, now=1.0, retry_after=10.0)  # longer than the 6s interval
    assert d.pop_due(10.9) is None  # nothing, not even a, until 1 + 10
    assert d.pop_due(11.0) is a  # back in front of b
    assert d.pop_due(17.0) is b


def run_gateway(gateway_limit, backend_limit, n):
    """Real mock backend and real threads; returns (tasks, gateway, events)."""
    events = []
    with real_sender(backend_limit) as sender:
        with Gateway(sender, FifoDispatcher(gateway_limit), on_event=events.append) as gw:
            tasks = [gw.submit(f"r{i}") for i in range(n)]
            assert all(t.wait(10) for t in tasks)
    return tasks, gw, events


def test_matched_limits_forward_in_order_without_a_single_429():
    tasks, gw, events = run_gateway(gateway_limit=600, backend_limit=600, n=4)
    assert [t.status for t in tasks] == [200] * 4 and gw.wasted_retries == 0
    sends = [e for e in events if e["event"] == "forward"]
    assert [e["request_id"] for e in sends] == ["r0", "r1", "r2", "r3"]
    assert all(b["t"] - a["t"] >= 0.1 - 1e-3 for a, b in zip(sends, sends[1:]))


def test_gateway_that_sends_too_fast_retries_through_429s_and_counts_them():
    tasks, gw, _ = run_gateway(gateway_limit=1200, backend_limit=600, n=3)  # sends 2x too fast
    assert [t.status for t in tasks] == [200] * 3
    assert gw.wasted_retries >= 1
    assert sum(t.attempts for t in tasks) == 3 + gw.wasted_retries
