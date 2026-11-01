from agents import BaselineAdapter, ExchangeAdapter
from pricing import Scorer, TaskMeta

META = TaskMeta("acme", enqueued_at=0.0, user_facing=True)  # scores 20 + 40 at time 0


class Recorder:
    def submit(self, *args):
        self.args = args
        return "task"


def test_baseline_priority_is_the_scorers_price_and_zero_without_a_scorer():
    gw = Recorder()
    BaselineAdapter(gw, Scorer(), clock=lambda: 0.0).submit("r1", META)
    assert gw.args == ("r1", 60)
    BaselineAdapter(gw).submit("r2", META)
    assert gw.args == ("r2", 0.0)


def test_exchange_bid_is_the_scorers_price_and_the_gateway_gets_the_meta_for_aging_and_budgets():
    gw = Recorder()
    ExchangeAdapter(gw, Scorer(), clock=lambda: 0.0).submit("r1", META)
    assert gw.args == ("r1", 60, META)
