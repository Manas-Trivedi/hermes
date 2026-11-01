"""The experiment: the same seeded workload under FIFO, priority with aging and the exchange.

For every seed and every variant (all agents honest, or one agent inflating
its urgency) the three conditions play the identical arrivals, one after the
other, and each is stored in Postgres as its own run with all its events. The
runs of one (seed, variant) are named "<name>/<variant>/seed<seed>", so the
dashboard's comparison shows the three side by side.

    uv run python -m experiments.runner --database postgresql://... --seeds 1,2,3

Runs are sequential on purpose: they share the machine's clock and CPU, and a
run that overlaps another would measure the overlap. A run that fails stays
unfinished (it is never reported) and the runner stops with the error, so a
half-done experiment cannot pass for a finished one.
"""

import argparse
from dataclasses import asdict, replace

from agents.workload import WorkloadConfig, generate
from experiments.conditions import CONDITIONS, Settings, run_condition
from store import EventWriter, connect, create_run, finish_run

HONEST = "honest"


def run_experiment(
    url: str,
    name: str,
    seeds: list[int],
    variants: dict[str, frozenset],
    settings: Settings = Settings(),
    workload: WorkloadConfig = WorkloadConfig(),
    log=print,
    conditions: tuple[str, ...] = CONDITIONS,
) -> list[int]:
    """Run each condition for every (seed, variant). Returns the ids of the runs stored."""
    if unknown := set(conditions) - set(CONDITIONS):
        raise ValueError(f"unknown conditions {sorted(unknown)}")  # before any run is stored
    run_ids = []
    for seed in seeds:
        arrivals = generate(seed, workload)  # one stream per seed, shared by every condition and variant
        for variant, inflate in variants.items():
            for condition in conditions:
                params = {**asdict(settings), **asdict(workload), "variant": variant, "inflate": sorted(inflate)}
                with connect(url) as conn:
                    run_id = create_run(conn, f"{name}/{variant}/seed{seed}", condition, seed, params)
                log(f"run {run_id}: seed {seed}, {variant}, {condition}, {len(arrivals)} items")
                with EventWriter(url, run_id) as writer:
                    results, wasted = run_condition(condition, arrivals, seed, settings, workload, inflate, on_event=writer)
                with connect(url) as conn:
                    finish_run(conn, run_id)
                log(f"  {sum(r.ok for r in results)}/{len(results)} items ok, {wasted} wasted retries")
                run_ids.append(run_id)
    return run_ids


def main() -> None:
    p = argparse.ArgumentParser(description="Run the experiment: FIFO, priority and exchange on the same workload")
    p.add_argument("--database", required=True)
    p.add_argument("--name", default="experiment")
    p.add_argument("--seeds", default="1,2,3", help="comma-separated")
    p.add_argument("--inflate", default="pr-review", help="the agent that inflates in the inflated variant; empty for honest only")
    p.add_argument("--duration", type=float, default=WorkloadConfig.duration, help="seconds over which new work arrives")
    d = Settings()
    p.add_argument("--limit", type=float, default=d.limit, help="backend calls per minute")
    p.add_argument("--median", type=float, default=d.median_latency, help="median backend latency in seconds")
    p.add_argument("--aging-rate", type=float, default=d.aging_rate, help="priority baseline: points per second waited")
    p.add_argument("--equal-share", action="store_true", help="exchange: split the credit pool equally between agents")
    p.add_argument("--conditions", default=",".join(CONDITIONS), help="comma-separated; a sweep of one setting only needs the condition it affects")
    p.add_argument("--pool", type=float, default=d.pool, help="exchange: credits per second across all agents")
    a = p.parse_args()

    variants = {HONEST: frozenset()}
    if a.inflate:
        variants[f"inflate-{a.inflate}"] = frozenset({a.inflate})
    settings = replace(d, limit=a.limit, median_latency=a.median, aging_rate=a.aging_rate, pool=a.pool, equal_share=a.equal_share)
    run_experiment(a.database, a.name, [int(s) for s in a.seeds.split(",")], variants, settings, WorkloadConfig(duration=a.duration),
                   conditions=tuple(a.conditions.split(",")))


if __name__ == "__main__":
    main()
