import json
import os
import threading
import time

import pytest

from client import Engine
from client.engine import DEFAULT_BINARY
from experiments.baselines import FifoDispatcher, Gateway, PriorityDispatcher
from experiments.tests.helpers import real_sender
from gateway import EventLog, ExchangeGateway, check_lifecycle

BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
pytestmark = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")


def run_scenario(kind):
    """One scenario on any gateway: a sent call, a cancel, and a gateway that sends
    twice as fast as the backend allows, so at least one call is rejected and retried."""
    log = EventLog()
    with Engine(arena=1000) as engine:
        backend_limit = 300 if kind == "exchange" else 600
        with real_sender(backend_limit) as sender:
            if kind == "exchange":
                gw = ExchangeGateway(sender, engine, 600, on_event=log)
            else:
                dispatcher = FifoDispatcher(1200) if kind == "fifo" else PriorityDispatcher(1200)
                gw = Gateway(sender, dispatcher, on_event=log)
            with gw:
                a = gw.submit("a", 5)
                while not any(e["event"] == "forward" for e in log.events):
                    time.sleep(0.001)
                b, dropped, c = gw.submit("b", 5), gw.submit("dropped", 1), gw.submit("c", 5)
                assert gw.cancel(dropped) is True
                assert all(t.wait(10) for t in (a, b, c, dropped))
    return log.events, gw


@pytest.mark.parametrize("kind", ["fifo", "priority", "exchange"])
def test_every_gateway_logs_the_same_shaped_sound_lifecycle(kind):
    events, gw = run_scenario(kind)
    assert check_lifecycle(events) == []
    assert all({"event", "gateway", "request_id", "t", "attempt"} <= e.keys() for e in events)
    assert {e["gateway"] for e in events} == {kind}
    assert sum(e["event"] == "rejected" for e in events) == gw.wasted_retries >= 1
    assert ({"bid", "fill"} & {e["event"] for e in events}) == ({"bid", "fill"} if kind == "exchange" else set())
    assert [e["status"] for e in events if e["event"] == "result"] == [200] * 3


def test_concurrent_writers_leave_every_line_whole_and_nothing_lost(tmp_path):
    path = tmp_path / "events.jsonl"

    with EventLog(path) as log:
        def write(worker):
            for i in range(200):
                log({"event": "request", "request_id": f"w{worker}-{i}", "t": float(i)})

        threads = [threading.Thread(target=write, args=(w,)) for w in range(8)]
        [t.start() for t in threads]
        [t.join() for t in threads]
    lines = path.read_text().splitlines()
    assert len(lines) == 1600 == len(log.events)
    assert len({json.loads(line)["request_id"] for line in lines}) == 1600


def ev(kind, rid="r", t=0.0, **kw):
    return {"event": kind, "gateway": "fifo", "request_id": rid, "t": t, "attempt": 0, **kw}


@pytest.mark.parametrize(
    "damaged",
    [
        [ev("request"), ev("forward", t=1)],  # never finished
        [ev("request"), ev("result", t=1)],  # a result with no forward
        [ev("forward"), ev("result", t=1)],  # no request
        [ev("request"), ev("forward", t=1), ev("result", t=2), ev("cancelled", t=3)],  # two endings
        [ev("request", t=5), ev("forward", t=1), ev("result", t=2)],  # time goes backwards
        [ev("request"), ev("fill", t=1), ev("forward", t=2), ev("rejected", t=3), ev("forward", t=4), ev("result", t=5)],
    ],  # the last: two forwards but only one fill
)
def test_lifecycle_check_catches_a_damaged_log(damaged):
    assert check_lifecycle(damaged) != []
