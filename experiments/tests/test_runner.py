import os

import pytest

from agents.workload import WorkloadConfig
from client.engine import DEFAULT_BINARY
from experiments.conditions import Settings
from experiments.runner import run_experiment
from store.tests.helpers import temp_schema

BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
pytestmark = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")

BUSY = WorkloadConfig(duration=3.0, pr_per_minute=60, pr_files=(2, 3), ticket_per_minute=60, research_per_minute=30, research_papers=(3, 4))
FAST = Settings(limit=600, median_latency=0.01)


def test_every_seed_and_variant_stores_three_finished_runs_over_the_identical_workload():
    with temp_schema() as (conn, url):
        variants = {"honest": frozenset(), "inflate-pr-review": frozenset({"pr-review"})}
        ids = run_experiment(url, "exp", [3], variants, FAST, BUSY, log=lambda _: None)
        assert len(ids) == 6
        rows = conn.execute(
            "SELECT r.name, r.condition, r.finished_at IS NOT NULL, r.params->>'variant', count(q.request_id),"
            " count(*) FILTER (WHERE q.outcome IS NULL)"
            " FROM experiment_runs r JOIN requests q ON q.run_id = r.id GROUP BY r.id ORDER BY r.id"
        ).fetchall()
        assert [(r[0], r[1]) for r in rows] == [
            (f"exp/{v}/seed3", c) for v in variants for c in ("fifo", "priority", "exchange")
        ]
        assert all(r[2] and r[5] == 0 for r in rows)  # finished, and no request left open
        by_variant = {}
        for name, _, _, variant, count, _ in rows:
            by_variant.setdefault(name, set()).add(count)
        assert all(len(counts) == 1 for counts in by_variant.values())  # the same number of requests under all three conditions
        assert {r[3] for r in rows} == set(variants)
