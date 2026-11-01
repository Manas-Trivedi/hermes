"""Runs the three agents through one gateway against the mock backend, with the live feed on.

Open the dashboard, point it at the feed, and the run starts when it connects:

    uv run python -m experiments.demo --gateway exchange --duration 120 --limit 20

With --database the events are also stored in Postgres, as a new experiment run.
"""

import argparse
import threading
import time

from agents import BaselineAdapter, ExchangeAdapter, PromptSender
from agents.workload import WorkloadConfig, build_agents, generate, run_workload
from client import Engine
from experiments.baselines import FifoDispatcher, Gateway, PriorityDispatcher
from experiments.mock_backend import MockBackend, make_server
from feed import EventFeed
from gateway import ExchangeGateway, HttpSender
from pricing import Scorer


def main() -> None:
    p = argparse.ArgumentParser(description="Mock flow: the three agents through one gateway, streamed live")
    p.add_argument("--gateway", choices=["exchange", "priority", "fifo"], default="exchange")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--duration", type=float, default=120.0, help="seconds over which new work arrives")
    p.add_argument("--limit", type=float, default=20.0, help="backend calls per minute (the workload wants about 27)")
    p.add_argument("--median", type=float, default=1.0, help="median backend latency in seconds")
    p.add_argument("--feed-port", type=int, default=8765)
    p.add_argument("--no-wait", action="store_true", help="start without waiting for a dashboard to connect")
    p.add_argument("--database", help="Postgres URL; also store the events as a new experiment run")
    a = p.parse_args()

    backend = MockBackend(a.limit, a.seed, a.median, tolerance=0.05)
    server = make_server(backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sender = PromptSender(HttpSender(f"http://127.0.0.1:{server.server_port}/v1/complete"))
    arrivals = generate(a.seed, WorkloadConfig(duration=a.duration))
    scorer = Scorer()

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
            if a.gateway == "exchange":
                rescore = lambda task, now: scorer.score(task.meta, now).price
                with Engine(arena=10000) as engine:
                    with ExchangeGateway(sender, engine, a.limit, on_event=on_event, rescore=rescore) as gw:
                        results = run_workload(arrivals, build_agents(ExchangeAdapter(gw, scorer), sender))
            else:
                dispatcher = FifoDispatcher(a.limit) if a.gateway == "fifo" else PriorityDispatcher(a.limit)
                with Gateway(sender, dispatcher, on_event=on_event) as gw:
                    adapter = BaselineAdapter(gw, scorer if a.gateway == "priority" else None)
                    results = run_workload(arrivals, build_agents(adapter, sender))
            finished = True
        finally:
            if writer:
                writer.close()
        if writer and finished:  # a run that failed stays unfinished, so it is never reported as a result
            with connect(a.database) as conn:
                finish_run(conn, run_id)
        print(f"done: {sum(r.ok for r in results)}/{len(results)} items ok, {gw.wasted_retries} wasted retries")
    server.shutdown()


if __name__ == "__main__":
    main()
