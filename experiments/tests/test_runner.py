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


def test_only_the_asked_conditions_run_and_a_typo_stores_nothing():
    with temp_schema() as (conn, url):
        ids = run_experiment(url, "exp", [1], {"honest": frozenset()}, FAST, BUSY, log=lambda _: None, conditions=("priority",))
        assert [r[0] for r in conn.execute("SELECT condition FROM experiment_runs").fetchall()] == ["priority"] and len(ids) == 1
        with pytest.raises(ValueError):
            run_experiment(url, "exp", [1], {"honest": frozenset()}, FAST, BUSY, log=lambda _: None, conditions=("priority", "exchnge"))
        assert conn.execute("SELECT count(*) FROM experiment_runs").fetchone()[0] == 1


def test_equal_share_gives_every_agent_the_same_credit_rate_and_the_default_does_not(monkeypatch):
    from agents.workload import generate
    from experiments import conditions

    seen = []
    real = conditions.Budgets
    monkeypatch.setattr(conditions, "Budgets", lambda *a, **k: seen.append(real(*a, **k)) or seen[-1])
    arrivals = generate(1, BUSY)
    for equal in (False, True):
        conditions.run_condition("exchange", arrivals, 1, Settings(limit=600, median_latency=0.01, equal_share=equal), BUSY)
    weighted, equal = (set(round(r, 6) for r in b.rates.values()) for b in seen)
    assert len(weighted) == 3 and len(equal) == 1
