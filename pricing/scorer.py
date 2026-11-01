"""Rules-based urgency scorer: a bid price plus the reason for every point of it.

The price is a sum of named contributions, so "why did B outbid A" is answered
by comparing two contribution dicts. There is no hidden term: price is exactly
the sum of the contributions, each rounded to whole ticks (the book trades in
integers).

    base          every task starts here
    user_facing   a person is waiting on the answer
    batched       one call of a bulk job; yields to interactive work (negative)
    deadline      rises from 0 to the full weight as slack falls from the
                  horizon to zero, and stays at the full weight once overdue
    wait          grows with time spent queued, so old work is never starved

Scoring the same task at a later time can only raise its price. That is what
aging (re-bidding a waiting task) relies on.

The weights are operator config. The defaults are placeholders, to be fixed
before any experiment run.
"""

from dataclasses import dataclass

from pricing.task import TaskMeta, features


@dataclass(frozen=True)
class Weights:
    base: int = 20
    user_facing: int = 40
    batched: int = -10
    deadline: int = 30  # most points the deadline can add
    deadline_horizon: float = 300.0  # seconds of slack at which the deadline starts to add points
    wait_per_second: float = 0.1

    def __post_init__(self):
        if self.user_facing < 0 or self.deadline < 0 or self.wait_per_second < 0:
            raise ValueError("user_facing, deadline and wait_per_second must not be negative")
        if self.deadline_horizon <= 0:
            raise ValueError("deadline_horizon must be positive")
        if self.base + self.batched < 1:
            raise ValueError("the lowest possible price (base + batched) must be at least 1")


@dataclass(frozen=True)
class Quote:
    price: int  # ticks; always at least 1
    contributions: dict[str, int]  # named terms; price is their sum. Only terms that apply appear.


class Scorer:
    def __init__(self, weights: Weights = Weights()):
        self._w = weights

    def score(self, meta: TaskMeta, now: float) -> Quote:
        w, f = self._w, features(meta, now)
        points: dict[str, float] = {"base": w.base}
        if f.user_facing:
            points["user_facing"] = w.user_facing
        if f.batched:
            points["batched"] = w.batched
        if f.slack is not None:
            pressure = min(1.0, max(0.0, 1.0 - f.slack / w.deadline_horizon))
            points["deadline"] = w.deadline * pressure
        if f.waited > 0:
            points["wait"] = w.wait_per_second * f.waited
        contributions = {name: round(p) for name, p in points.items()}
        return Quote(sum(contributions.values()), contributions)
