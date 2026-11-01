"""The seeded workload: the same three agents' work, identical on every run.

`generate` turns a seed into a list of timed arrivals, one item of work at a
time, so the FIFO, priority and exchange conditions all face the same stream.
Each agent draws from its own random stream (seeded by the seed and its name),
so changing one agent's rate or size leaves the other two agents' work exactly
as it was. `run_workload` plays the arrivals into a set of agents, each item
on its own thread, and returns what happened to every item.

The prompts are filler words. The mock backend ignores content, and what the
scheduling experiment varies is when each call arrives and how urgent it is.
`expected_demand` and `WEIGHTS` give the credit budgets their inputs (4.5).
"""

import random
import threading
import time
from dataclasses import dataclass

from agents.base import Agent, ItemResult, PromptSender
from agents.pr_review import PrReviewAgent, PullRequest
from agents.research import ResearchAgent, ResearchTask
from agents.support import SupportAgent, Ticket
from pricing import AgentConfig

WEIGHTS = {"support": 3.0, "research": 2.0, "pr-review": 1.0}  # how much the business values each agent

_WORDS = "request error cache latency user order refund config deploy token queue retry timeout index schema".split()


@dataclass(frozen=True)
class WorkloadConfig:
    duration: float = 120.0  # seconds over which new work arrives
    pr_per_minute: float = 2.0
    pr_files: tuple[int, int] = (2, 6)  # changed files per PR, inclusive
    ticket_per_minute: float = 6.0
    research_per_minute: float = 1.0
    research_papers: tuple[int, int] = (4, 10)  # papers per research task, inclusive


@dataclass(frozen=True)
class Arrival:
    at: float  # seconds after the run starts
    agent: str
    item: object


def generate(seed: int, config: WorkloadConfig = WorkloadConfig()) -> list[Arrival]:
    c = config
    arrivals = []
    for agent, per_minute, make in [
        ("pr-review", c.pr_per_minute, lambda rng, n: PullRequest(f"pr{n}", tuple(_text(rng) for _ in range(rng.randint(*c.pr_files))))),
        ("support", c.ticket_per_minute, lambda rng, n: Ticket(f"t{n}", _text(rng))),
        ("research", c.research_per_minute, lambda rng, n: ResearchTask(f"q{n}", _text(rng, 6), tuple(_text(rng) for _ in range(rng.randint(*c.research_papers))))),
    ]:
        rng = random.Random(f"{seed}:{agent}")
        t, n = 0.0, 0
        while per_minute > 0:
            t += rng.expovariate(per_minute / 60.0)  # Poisson arrivals
            if t >= c.duration:
                break
            arrivals.append(Arrival(t, agent, make(rng, n)))
            n += 1
    return sorted(arrivals, key=lambda a: a.at)


def _text(rng: random.Random, words: int | None = None) -> str:
    return " ".join(rng.choices(_WORDS, k=words or rng.randint(20, 200)))


def expected_demand(config: WorkloadConfig = WorkloadConfig()) -> dict[str, float]:
    """Expected backend calls per minute from each agent (each item makes its inputs plus one)."""
    mean = lambda r: (r[0] + r[1]) / 2
    return {
        "pr-review": config.pr_per_minute * (mean(config.pr_files) + 1),
        "support": config.ticket_per_minute * 2,
        "research": config.research_per_minute * (mean(config.research_papers) + 1),
    }


def agent_configs(config: WorkloadConfig = WorkloadConfig()) -> dict[str, AgentConfig]:
    """The budget inputs for 4.5: demand from the workload, weight from the business."""
    return {name: AgentConfig(demand, WEIGHTS[name]) for name, demand in expected_demand(config).items()}


def build_agents(adapter, sender: PromptSender, tenant_id: str = "default", inflate=frozenset(), **kw) -> dict[str, Agent]:
    """The three agents by name. Those named in `inflate` declare maximum urgency on every call."""
    classes = (PrReviewAgent, SupportAgent, ResearchAgent)
    return {c.name: c(adapter, sender, tenant_id, c.name in inflate, **kw) for c in classes}


def run_workload(arrivals: list[Arrival], agents: dict[str, Agent], clock=time.monotonic, sleep=time.sleep) -> list[ItemResult]:
    """Play the arrivals at their times and wait for every item to finish."""
    results: list[ItemResult] = []
    lock = threading.Lock()

    def work(arrival: Arrival) -> None:
        result = agents[arrival.agent].run(arrival.item)
        with lock:
            results.append(result)

    start, threads = clock(), []
    for arrival in arrivals:
        wait = start + arrival.at - clock()
        if wait > 0:
            sleep(wait)
        t = threading.Thread(target=work, args=(arrival,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    return results
