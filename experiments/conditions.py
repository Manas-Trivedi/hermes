"""One experiment condition: the three agents' workload through one gateway.

The three conditions share everything but the gateway: the same arrivals, the
same mock backend (a fresh one, with the same seed, so each request id sees the
same latency whatever the order), the same limit, the same agents, and the same
urgency scorer. FIFO ignores the scorer's price, the priority baseline sorts on
it with aging, and the exchange bids it under credit budgets.
"""

import threading
import time
from dataclasses import dataclass

from agents import BaselineAdapter, ExchangeAdapter, PromptSender
from agents.base import ItemResult
from agents.workload import Arrival, WorkloadConfig, agent_configs, build_agents, run_workload
from client import Engine
from experiments.baselines import FifoDispatcher, Gateway, PriorityDispatcher
from experiments.mock_backend import MockBackend, make_server
from gateway import ExchangeGateway, HttpSender
from pricing import Budgets, Scorer

CONDITIONS = ("fifo", "priority", "exchange")


@dataclass(frozen=True)
class Settings:
    limit: float = 20.0  # backend calls per minute, for the backend and for every gateway
    median_latency: float = 1.0
    aging_rate: float = 1.0  # priority baseline: points per second waited (swept in 8.3)
    pool: float = 10.0  # exchange: credits per second across all agents (see pricing.budget)
    cap_seconds: float = 60.0
    reprice_interval: float = 1.0


def run_condition(
    condition: str,
    arrivals: list[Arrival],
    seed: int,
    settings: Settings = Settings(),
    workload: WorkloadConfig = WorkloadConfig(),
    inflate=frozenset(),
    on_event=None,
) -> tuple[list[ItemResult], int]:
    """Play `arrivals` through the named gateway. Returns the results and the wasted retries."""
    if condition not in CONDITIONS:
        raise ValueError(f"unknown condition {condition!r}")
    s = settings
    server = make_server(MockBackend(s.limit, seed, s.median_latency, tolerance=0.05))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    sender = PromptSender(HttpSender(f"http://127.0.0.1:{server.server_port}/v1/complete"))
    scorer = Scorer()
    try:
        if condition == "exchange":
            rescore = lambda task, now: scorer.score(task.meta, now).price
            budgets = Budgets(agent_configs(workload), time.monotonic(), s.pool, s.cap_seconds)
            with Engine(arena=10000) as engine:
                with ExchangeGateway(
                    sender, engine, s.limit, on_event=on_event, rescore=rescore, reprice_interval=s.reprice_interval, budgets=budgets
                ) as gw:
                    results = run_workload(arrivals, build_agents(ExchangeAdapter(gw, scorer), sender, inflate=inflate))
        else:
            dispatcher = FifoDispatcher(s.limit) if condition == "fifo" else PriorityDispatcher(s.limit, s.aging_rate)
            with Gateway(sender, dispatcher, on_event=on_event) as gw:
                adapter = BaselineAdapter(gw, scorer if condition == "priority" else None)
                results = run_workload(arrivals, build_agents(adapter, sender, inflate=inflate))
        return results, gw.wasted_retries
    finally:
        server.shutdown()
        server.server_close()
