from experiments.report import experiment_of, paired, report
from store import create_run, finish_run
from store.tests.helpers import temp_schema


def stored(conn, name, condition, seed, latency):
    run = create_run(conn, name, condition, seed)
    conn.execute(
        "INSERT INTO requests (run_id, request_id, gateway, t_request, t_end, outcome, status)"
        " VALUES (%s, 'support-t1', 'x', 0, %s, 'result', 200)", (run, latency))
    conn.commit()
    finish_run(conn, run)


def test_paired_counts_seeds_where_the_exchange_is_strictly_better_and_a_tie_is_not_a_win():
    runs = [
        {"seed": 1, "condition": "exchange", "p95_latency": 1.0, "completion_time": 5.0, "failures": 0, "wasted_retries": 0},
        {"seed": 1, "condition": "fifo", "p95_latency": 2.0, "completion_time": 5.0, "failures": 1, "wasted_retries": 0},
        {"seed": 2, "condition": "exchange", "p95_latency": 3.0, "completion_time": 5.0, "failures": 0, "wasted_retries": 0},
        {"seed": 2, "condition": "fifo", "p95_latency": 2.0, "completion_time": 5.0, "failures": 0, "wasted_retries": 0},
    ]
    (line,) = paired(runs)
    assert "P95 s 1/2" in line and "completion s 0/2" in line and "failures 1/2" in line


def test_report_groups_the_seeds_of_one_experiment_and_splits_by_agent():
    assert experiment_of("main/honest/seed12") == "main/honest"
    with temp_schema() as (conn, _):
        stored(conn, "main/honest/seed1", "fifo", 1, 2.0)
        stored(conn, "main/honest/seed2", "fifo", 2, 4.0)
        text = report(conn)
        assert text.count("### ") == 1
        assert "| fifo | 2 | 3.0 (2.0–4.0) |" in text  # completion time, mean and range over the two seeds
        assert "support / fifo" in text
