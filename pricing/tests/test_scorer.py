import pytest

from pricing import Scorer, TaskMeta, Weights


def test_price_is_exactly_the_sum_of_the_contributions_even_when_terms_round():
    w = Weights(deadline=7, wait_per_second=0.13)
    meta = TaskMeta("t", enqueued_at=0.0, deadline=100.0, user_facing=True, batch_id="b")
    for now in (0.0, 37.0, 99.9, 250.0):
        q = Scorer(w).score(meta, now)
        assert q.price == sum(q.contributions.values())


def test_deadline_adds_nothing_before_the_horizon_and_the_full_weight_once_overdue():
    s = Scorer(Weights(deadline=30, deadline_horizon=300.0, wait_per_second=0.0))
    meta = TaskMeta("t", enqueued_at=0.0, deadline=1000.0)
    assert s.score(meta, 600.0).contributions["deadline"] == 0  # 400s of slack
    assert s.score(meta, 850.0).contributions["deadline"] == 15  # 150s of slack, half the horizon
    assert s.score(meta, 1500.0).contributions["deadline"] == 30  # overdue


def test_only_the_terms_that_apply_are_listed():
    q = Scorer().score(TaskMeta("t", enqueued_at=5.0), 5.0)
    assert q.contributions == {"base": 20}


def test_weights_that_could_price_below_one_are_refused():
    with pytest.raises(ValueError):
        Weights(base=5, batched=-5)
