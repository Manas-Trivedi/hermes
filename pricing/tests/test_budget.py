import pytest

from pricing import AgentConfig, Budgets


def make(**kw):
    agents = {"a": AgentConfig(demand=10, weight=3), "b": AgentConfig(demand=30, weight=1), "c": AgentConfig(demand=5, weight=2)}
    return Budgets(agents, pool=100.0, start=0.0, **kw)


def test_rates_split_the_pool_by_demand_times_weight_whatever_the_units():
    b = make()  # shares 30, 30, 10
    assert b.rates == pytest.approx({"a": 42.857142, "b": 42.857142, "c": 14.285714})
    assert sum(b.rates.values()) == pytest.approx(100.0)
    scaled = Budgets({"a": AgentConfig(70, 1), "b": AgentConfig(210, 1 / 3), "c": AgentConfig(35, 2 / 3)}, start=0.0, pool=100.0)
    assert scaled.rates == pytest.approx(b.rates)


def test_defaults_split_the_pool_equally_among_agents_given_no_demand_or_weight():
    b = Budgets({"a": AgentConfig(), "b": AgentConfig()}, start=0.0)
    assert b.rates == {"a": 5.0, "b": 5.0} and b.balance("a", 0.0) == 300  # a pool of 10, 60s cap


def test_config_that_gives_nobody_a_share_is_refused():
    with pytest.raises(ValueError):
        Budgets({"a": AgentConfig(demand=10, weight=0)}, pool=1.0, start=0.0)


def test_balance_starts_full_regenerates_and_carries_over_only_up_to_the_cap():
    b = Budgets({"a": AgentConfig(1, 1)}, pool=2.0, start=0.0, cap_seconds=10.0)  # 2/s, cap 20
    assert b.balance("a", 0.0) == 20
    b.hold("x", "a", 20)
    b.settle("x", 20, 0.0)
    assert b.balance("a", 0.0) == 0
    assert b.balance("a", 4.0) == pytest.approx(8.0)
    assert b.balance("a", 1000.0) == 20  # unused credits stop at the cap


def test_a_hold_reduces_what_the_agents_other_bids_can_offer_until_it_is_released():
    b = Budgets({"a": AgentConfig(1, 1)}, pool=1.0, start=0.0, cap_seconds=100.0)  # balance 100
    b.hold("x", "a", 70)
    assert b.available("y", "a", 0.0) == 30
    assert b.available("x", "a", 0.0) == 100  # its own hold counts as free when it re-bids
    b.release("x")
    assert b.available("y", "a", 0.0) == 100


def test_winning_spends_the_price_paid_not_the_hold():
    b = Budgets({"a": AgentConfig(1, 1)}, pool=1.0, start=0.0, cap_seconds=100.0)
    b.hold("x", "a", 80)
    b.settle("x", 30, 0.0)  # won at a price below the bid
    assert b.balance("a", 0.0) == 70 and b.available("y", "a", 0.0) == 70


def test_time_until_a_price_is_affordable_follows_the_refill_rate():
    b = Budgets({"a": AgentConfig(1, 1)}, pool=2.0, start=0.0, cap_seconds=10.0)  # 2/s, cap 20
    b.hold("x", "a", 20)
    assert b.available("y", "a", 0.0) == 0
    assert b.seconds_until("y", "a", 1, 0.0) == pytest.approx(0.5)
    assert b.seconds_until("x", "a", 20, 0.0) == 0.0  # its own hold is free to it



def test_a_restart_gets_back_what_was_saved_plus_what_regenerated_while_it_was_away_up_to_the_cap():
    def fresh():
        return Budgets({"a": AgentConfig(1, 1), "b": AgentConfig(1, 1)}, pool=2.0, start=0.0, cap_seconds=10.0)  # 1/s each, cap 10

    old = fresh()
    old.hold("bid", "a", 5)
    old.settle("bid", 5, now=0.0)
    assert old.snapshot(now=3.0) == {"a": 8.0, "b": 10.0}  # 10 - 5 + 3 regenerated; b is full

    new = fresh()
    new.restore({"a": 8.0, "ghost": 3.0}, away={"a": 1.0, "ghost": 9.0}, now=100.0)  # the ghost is no longer configured
    assert new.balance("a", 100.0) == 9.0 and new.balance("b", 100.0) == 10.0  # b was never saved, so it starts full
    assert new.balance("a", 110.0) == 10.0  # and regenerates on from the restart
    new.restore({"a": 9.5}, away={"a": 600.0}, now=100.0)
    assert new.balance("a", 100.0) == 10.0  # a long absence cannot overfill it
