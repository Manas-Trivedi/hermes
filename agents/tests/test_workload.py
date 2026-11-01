from dataclasses import replace

from agents import ExchangeAdapter, PromptSender
from agents.tests.helpers import FakeAdapter
from agents.workload import WorkloadConfig, agent_configs, build_agents, expected_demand, generate, run_workload
from client import Engine
from experiments.tests.helpers import real_sender
from gateway import EventLog, ExchangeGateway, check_lifecycle
from pricing import Scorer

CONFIG = WorkloadConfig(duration=300.0)


def test_the_same_seed_gives_the_same_workload_in_time_order_and_another_seed_a_different_one():
    a = generate(7, CONFIG)
    assert a == generate(7, CONFIG) and a != generate(8, CONFIG)
    assert [x.at for x in a] == sorted(x.at for x in a) and all(0 <= x.at < 300 for x in a)
    assert {x.agent for x in a} == {"pr-review", "support", "research"}


def test_changing_one_agents_rate_leaves_the_other_agents_work_untouched():
    base = generate(7, CONFIG)
    busier = generate(7, replace(CONFIG, ticket_per_minute=30.0))
    others = lambda arrivals: [x for x in arrivals if x.agent != "support"]
    assert others(base) == others(busier) and len(busier) > len(base)


def test_expected_demand_counts_each_items_inputs_plus_its_final_call_and_feeds_the_budgets():
    c = WorkloadConfig(pr_per_minute=2, pr_files=(2, 4), ticket_per_minute=6, research_per_minute=1, research_papers=(4, 8))
    assert expected_demand(c) == {"pr-review": 2 * 4, "support": 6 * 2, "research": 1 * 7}
    assert agent_configs(c)["support"].weight > agent_configs(c)["pr-review"].weight


def test_only_the_named_agents_inflate():
    adapter = FakeAdapter()
    agents = build_agents(adapter, PromptSender(None), inflate={"pr-review"})
    for arrival in generate(1, replace(CONFIG, duration=60.0)):
        agents[arrival.agent].run(arrival.item)
    by_agent = {m.agent_id: m for _, m in adapter.submitted}
    assert by_agent["pr-review"].user_facing is True  # inflated, though it is a background agent
    assert by_agent["research"].user_facing is False and by_agent["support"].user_facing is True
    assert by_agent["pr-review"].deadline == by_agent["pr-review"].enqueued_at


def test_the_three_agents_run_together_against_the_exchange_and_every_item_completes():
    config = WorkloadConfig(duration=3.0, pr_per_minute=60, pr_files=(2, 3), ticket_per_minute=60,
                            research_per_minute=30, research_papers=(3, 4))
    arrivals = generate(3, config)
    events = EventLog()
    scorer = Scorer()
    with Engine(arena=1000) as engine, real_sender(600, tolerance=0.05) as http:
        sender = PromptSender(http)
        rescore = lambda task, now: scorer.score(task.meta, now).price
        with ExchangeGateway(sender, engine, 600, on_event=events, rescore=rescore, reprice_interval=0.2) as gw:
            agents = build_agents(ExchangeAdapter(gw, scorer), sender, tenant_id="acme")
            results = run_workload(arrivals, agents)
    assert len(results) == len(arrivals) and all(r.ok for r in results)
    assert {r.agent for r in results} == {"pr-review", "support", "research"}
    assert check_lifecycle(events.events) == []
