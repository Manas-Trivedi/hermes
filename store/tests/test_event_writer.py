import os

import pytest

from client.engine import DEFAULT_BINARY
from gateway.tests.test_events import run_scenario
from store import EventWriter, create_run
from store.tests.helpers import temp_schema

BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
needs_engine = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")


def write_all(url, run_id, events):
    with EventWriter(url, run_id) as writer:
        for e in events:
            writer(e)


def ev(kind, rid, t, attempt=0, **fields):
    return {"event": kind, "gateway": "exchange", "request_id": rid, "t": t, "attempt": attempt, **fields}


def test_one_request_with_a_rejected_call_is_spread_over_the_tables():
    events = [
        ev("request", "a", 0.0),
        ev("bid", "a", 0.1, offered=7, asked=9),
        ev("reprice", "a", 0.2, offered=8, previous=7),
        ev("fill", "a", 0.3, paid=8, offered=8),
        ev("forward", "a", 0.3, attempt=1),
        ev("rejected", "a", 0.4, attempt=1),
        ev("bid", "a", 0.4, attempt=1, offered=8, asked=8),
        ev("fill", "a", 0.5, attempt=1, paid=8, offered=8),
        ev("forward", "a", 0.5, attempt=2),
        ev("result", "a", 0.6, attempt=2, status=200, error=None),
    ]
    with temp_schema() as (conn, url):
        run_id = create_run(conn, "r", "exchange", seed=3, params={"limit": 60})
        write_all(url, run_id, events)
        assert conn.execute("SELECT outcome, status, t_request, t_end, forwards, rejections FROM requests").fetchall() == [
            ("result", 200, 0.0, 0.6, 2, 1)
        ]
        assert conn.execute("SELECT kind, attempt, offered, asked, previous FROM orders ORDER BY id").fetchall() == [
            ("bid", 0, 7, 9, None),
            ("reprice", 0, 8, None, 7),
            ("bid", 1, 8, 8, None),
        ]
        assert conn.execute("SELECT attempt, paid, offered FROM fills ORDER BY id").fetchall() == [(0, 8, 8), (1, 8, 8)]


def test_a_cancelled_request_and_a_failed_send_are_recorded():
    events = [
        ev("request", "c", 0.0),
        ev("cancelled", "c", 0.1),
        ev("request", "e", 0.0),
        ev("forward", "e", 0.1, attempt=1),
        ev("result", "e", 0.2, attempt=1, status=None, error="connection refused"),
    ]
    with temp_schema() as (conn, url):
        run_id = create_run(conn, "r", "fifo")
        write_all(url, run_id, events)
        assert conn.execute("SELECT request_id, outcome, status, error FROM requests ORDER BY request_id").fetchall() == [
            ("c", "cancelled", None, None),
            ("e", "result", None, "connection refused"),
        ]


def test_a_failed_write_is_raised_on_close_not_swallowed():
    with temp_schema() as (conn, url):
        run_id = create_run(conn, "r", "fifo")
        writer = EventWriter(url, run_id)
        writer(ev("forward", "never-requested", 0.0))
        writer(ev("request", "later", 0.1))
        with pytest.raises(RuntimeError, match="events were lost"):
            writer.close()


@needs_engine
@pytest.mark.parametrize("kind", ["fifo", "priority", "exchange"])
def test_a_real_gateway_run_is_stored_as_the_log_counts_it(kind):
    events, _ = run_scenario(kind)
    count = lambda name: sum(e["event"] == name for e in events)
    with temp_schema() as (conn, url):
        run_id = create_run(conn, "r", kind)
        write_all(url, run_id, events)
        row = conn.execute(
            "SELECT count(*), count(*) FILTER (WHERE outcome = 'cancelled'), sum(forwards), sum(rejections),"
            " count(*) FILTER (WHERE outcome IS NULL) FROM requests"
        ).fetchone()
        assert row == (count("request"), count("cancelled"), count("forward"), count("rejected"), 0)
        assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == count("bid") + count("reprice")
        assert conn.execute("SELECT count(*) FROM fills").fetchone()[0] == count("fill")
