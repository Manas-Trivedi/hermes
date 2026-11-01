"""Runs the three agents through one gateway against the mock backend, with the live feed on.

Open the dashboard, point it at the feed, and the run starts when it connects:

    uv run python -m experiments.demo --gateway exchange --duration 120 --limit 20

With --database the events are also stored in Postgres, as a new experiment run.
"""

import argparse
import time

from agents.workload import WorkloadConfig, generate
from experiments.conditions import CONDITIONS, Settings, run_condition
from feed import EventFeed


def main() -> None:
    p = argparse.ArgumentParser(description="Mock flow: the three agents through one gateway, streamed live")
    p.add_argument("--gateway", choices=CONDITIONS, default="exchange")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--duration", type=float, default=120.0, help="seconds over which new work arrives")
    p.add_argument("--limit", type=float, default=20.0, help="backend calls per minute (the workload wants about 27)")
    p.add_argument("--median", type=float, default=1.0, help="median backend latency in seconds")
    p.add_argument("--feed-port", type=int, default=8765)
    p.add_argument("--no-wait", action="store_true", help="start without waiting for a dashboard to connect")
    p.add_argument("--database", help="Postgres URL; also store the events as a new experiment run")
    a = p.parse_args()

    settings = Settings(limit=a.limit, median_latency=a.median)
    arrivals = generate(a.seed, WorkloadConfig(duration=a.duration))

    sinks = []
    writer = None
    finished = False
    with EventFeed(port=a.feed_port) as feed:
        sinks.append(feed)
        if a.database:
            from store import EventWriter, connect, create_run, finish_run

            with connect(a.database) as conn:
                run_id = create_run(conn, "demo", a.gateway, seed=a.seed, params=vars(a))
            writer = EventWriter(a.database, run_id)
            sinks.append(writer)
        on_event = lambda e: [s(e) for s in sinks]

        print(f"feed on ws://127.0.0.1:{feed.port}")
        if not a.no_wait:
            print("waiting for a dashboard to connect...")
            while feed.clients == 0:
                time.sleep(0.1)
        print(f"running {len(arrivals)} items through the {a.gateway} gateway")

        try:
            results, wasted = run_condition(a.gateway, arrivals, a.seed, settings, on_event=on_event)
            finished = True
        finally:
            if writer:
                writer.close()
        if writer and finished:  # a run that failed stays unfinished, so it is never reported as a result
            with connect(a.database) as conn:
                finish_run(conn, run_id)
        print(f"done: {sum(r.ok for r in results)}/{len(results)} items ok, {wasted} wasted retries")


if __name__ == "__main__":
    main()
