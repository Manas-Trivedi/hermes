import json
import threading
import urllib.request

import pytest

from store import create_run, finish_run
from store.api import make_server, run_summaries
from store.tests.helpers import temp_schema


def add(conn, run_id, rid, t0, t_end, outcome, status, rejections=0):
    conn.execute(
        "INSERT INTO requests (run_id, request_id, gateway, t_request, t_end, outcome, status, rejections)"
        " VALUES (%s, %s, 'exchange', %s, %s, %s, %s, %s)",
        (run_id, rid, t0, t_end, outcome, status, rejections),
    )
    conn.commit()


def seeded(conn):
    run = create_run(conn, "exp", "exchange", seed=1)
    add(conn, run, "a", 10.0, 12.0, "result", 200, rejections=1)
    add(conn, run, "b", 10.0, 14.0, "result", 200)
    add(conn, run, "c", 11.0, 20.0, "result", 500)
    add(conn, run, "d", 11.0, 13.0, "cancelled", None, rejections=2)
    finish_run(conn, run)
    return run


def test_a_run_is_summarised_to_the_numbers_the_chart_compares():
    with temp_schema() as (conn, _):
        seeded(conn)
        (row,) = run_summaries(conn)
        assert (row["condition"], row["requests"], row["completed"], row["failures"], row["wasted_retries"]) == ("exchange", 4, 2, 2, 3)
        assert row["completion_time"] == 10.0  # 10 -> 20
        assert row["p95_latency"] == pytest.approx(8.5)  # over the results' 2, 4 and 9 seconds


def test_p95_is_over_results_only():
    with temp_schema() as (conn, _):
        run = create_run(conn, "exp", "fifo")
        for i, latency in enumerate([1.0, 2.0, 3.0, 4.0]):
            add(conn, run, f"r{i}", 0.0, latency, "result", 200)
        add(conn, run, "slow-cancel", 0.0, 100.0, "cancelled", None)
        finish_run(conn, run)
        assert run_summaries(conn)[0]["p95_latency"] == pytest.approx(3.85)  # 1, 2, 3, 4: the cancel's 100s is not a latency


def test_a_run_that_never_finished_is_not_reported():
    with temp_schema() as (conn, _):
        run = create_run(conn, "exp", "exchange")
        add(conn, run, "a", 0.0, 1.0, "result", 200)
        assert run_summaries(conn) == []


def test_runs_are_served_as_json_to_a_page_on_another_port():
    with temp_schema() as (conn, url):
        seeded(conn)
        server = make_server(url, port=0)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/runs") as r:
                assert r.headers["Access-Control-Allow-Origin"] == "*"
                assert json.load(r)["runs"][0]["wasted_retries"] == 3
        finally:
            server.shutdown()
            server.server_close()
