import xml.dom.minidom

from experiments.chart import collect, render
from store import create_run, finish_run
from store.tests.helpers import temp_schema


def test_the_chart_is_valid_svg_that_shows_each_mean_and_survives_odd_names():
    data = {"honest": {"support": {"fifo": [10.0, 20.0], "priority": [5.0], "exchange": [8.0, 12.0]}},
            "inflate-a<b&c": {"support": {"fifo": [1.0]}}}
    svg = render(data)
    xml.dom.minidom.parseString(svg)  # well formed, so the escaped variant name did not break it
    assert ">15.0<" in svg and ">5.0<" in svg and ">10.0<" in svg  # the means, printed on the bars
    assert "a&lt;b&amp;c" in svg


def test_collect_groups_each_agents_p95_by_variant_and_condition_across_seeds_and_ignores_other_experiments():
    with temp_schema() as (conn, _):
        for name, latency in [("main/honest/seed1", 2.0), ("main/honest/seed2", 4.0), ("other/honest/seed1", 99.0)]:
            run = create_run(conn, name, "fifo")
            conn.execute("INSERT INTO requests (run_id, request_id, gateway, t_request, t_end, outcome, status)"
                         " VALUES (%s, 'support-t1', 'x', 0, %s, 'result', 200)", (run, latency))
            conn.commit()
            finish_run(conn, run)
        assert collect(conn, "main") == {"honest": {"support": {"fifo": [2.0, 4.0]}}}
