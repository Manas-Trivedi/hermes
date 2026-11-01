"""Print the stored experiment results as tables, to read them without the dashboard.

    uv run python -m experiments.report --database postgresql://...

Each experiment ("<name>/<variant>", the runs of its seeds being repeats) gets a
table of the mean over seeds with the lowest and highest in brackets, a table per
agent, and a paired check: seed by seed, how often the exchange did better than
each baseline. A tie is not a win. Only finished runs are read (store.api).
"""

import argparse
import re
from collections import defaultdict
from statistics import mean

from store.api import agent_summaries, run_summaries
from store.db import connect

CONDITIONS = ("fifo", "priority", "exchange")
METRICS = (("completion_time", "completion s"), ("p95_latency", "P95 s"), ("failures", "failures"), ("wasted_retries", "wasted"))


def experiment_of(run_name: str) -> str:
    return re.sub(r"/seed\d+$", "", run_name)


def cell(rows: list[dict], key: str) -> str:
    values = [r[key] for r in rows if r[key] is not None]
    if not values:
        return "–"
    if len(values) == 1:
        return f"{values[0]:.1f}"
    return f"{mean(values):.1f} ({min(values):.1f}–{max(values):.1f})"


def table(groups: dict[str, list[dict]], first: str) -> list[str]:
    lines = [f"| {first} | runs | " + " | ".join(t for _, t in METRICS) + " |", "|---|---|" + "---|" * len(METRICS)]
    for label, rows in groups.items():
        lines.append(f"| {label} | {len(rows)} | " + " | ".join(cell(rows, k) for k, _ in METRICS) + " |")
    return lines


def paired(runs: list[dict]) -> list[str]:
    """Per seed, does the exchange have a lower number than each baseline? Lower is better for every metric."""
    by_seed: dict[int, dict[str, dict]] = defaultdict(dict)
    for r in runs:
        by_seed[r["seed"]][r["condition"]] = r
    lines = []
    for other in ("fifo", "priority"):
        seeds = [s for s in by_seed.values() if "exchange" in s and other in s]
        if not seeds:
            continue
        wins = []
        for key, title in METRICS:
            both = [(s["exchange"][key], s[other][key]) for s in seeds if s["exchange"][key] is not None and s[other][key] is not None]
            wins.append(f"{title} {sum(a < b for a, b in both)}/{len(both)}")
        lines.append(f"- exchange better than {other}, seed by seed: " + ", ".join(wins))
    return lines


def report(conn) -> str:
    runs = run_summaries(conn)
    agents = agent_summaries(conn)
    condition_of = {r["id"]: r["condition"] for r in runs}
    out = []
    for name in dict.fromkeys(experiment_of(r["name"]) for r in runs):
        mine = [r for r in runs if experiment_of(r["name"]) == name]
        ids = {r["id"] for r in mine}
        out += [f"### {name}", ""]
        out += table({c: [r for r in mine if r["condition"] == c] for c in CONDITIONS if any(r["condition"] == c for r in mine)}, "condition")
        out += [""] + paired(mine) + [""]
        per_agent = {}
        for agent in dict.fromkeys(a["agent"] for a in agents if a["run_id"] in ids):
            for c in CONDITIONS:
                rows = [a for a in agents if a["agent"] == agent and a["run_id"] in ids and condition_of[a["run_id"]] == c]
                if rows:
                    per_agent[f"{agent} / {c}"] = rows
        out += table(per_agent, "agent / condition") + [""]
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(description="Print stored experiment results")
    p.add_argument("--database", required=True)
    a = p.parse_args()
    with connect(a.database) as conn:
        print(report(conn))


if __name__ == "__main__":
    main()
