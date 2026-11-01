"""The default weights, pinned through the questions an operator will ask:
why did B outbid A, and what does waiting buy."""

from pricing import Scorer, TaskMeta

scorer = Scorer()


def why(winner, loser):
    """Points by which each term favors the winner over the loser; terms that tie are left out."""
    a, b = winner.contributions, loser.contributions
    diff = {k: a.get(k, 0) - b.get(k, 0) for k in a.keys() | b.keys()}
    return {k: v for k, v in diff.items() if v}


def test_support_ticket_outbids_pr_review_because_a_person_is_waiting_and_the_deadline_is_close():
    ticket = scorer.score(TaskMeta("acme", enqueued_at=0.0, deadline=120.0, user_facing=True), 0.0)
    review = scorer.score(TaskMeta("acme", enqueued_at=0.0, deadline=3600.0), 0.0)
    assert ticket.price == 78 and review.price == 20
    assert why(ticket, review) == {"user_facing": 40, "deadline": 18}


def test_a_call_of_a_bulk_job_prices_below_the_same_call_on_its_own_by_exactly_the_batch_discount():
    alone = scorer.score(TaskMeta("acme", enqueued_at=0.0, deadline=200.0), 0.0)
    batched = scorer.score(TaskMeta("acme", enqueued_at=0.0, deadline=200.0, batch_id="b1"), 0.0)
    assert why(alone, batched) == {"batched": 10}


def test_a_review_that_has_waited_long_enough_outbids_a_fresh_ticket_and_waiting_is_why():
    review = scorer.score(TaskMeta("acme", enqueued_at=0.0), 1000.0)  # queued for 1000s
    ticket = scorer.score(TaskMeta("acme", enqueued_at=1000.0, deadline=1120.0, user_facing=True), 1000.0)
    assert review.price > ticket.price
    assert why(review, ticket) == {"wait": 100, "user_facing": -40, "deadline": -18}


def test_a_task_never_scores_lower_later_which_is_what_lets_aging_only_raise_bids():
    meta = TaskMeta("acme", enqueued_at=0.0, deadline=500.0, user_facing=True, batch_id="b1")
    prices = [scorer.score(meta, now).price for now in range(0, 1000, 7)]
    assert prices == sorted(prices) and prices[-1] > prices[0]
