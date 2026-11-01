"""Credit budgets: what makes urgency cost something.

Every agent has a balance that regenerates at a fixed rate and is capped, so
unused credits carry over but cannot pile up without limit. A bid can offer no
more than the agent can afford, a bid holds its credits while it rests in the
book (so one balance cannot back many bids at once), and a win spends the price
it paid. A bid's hold never exceeds the balance, so there is no overdraft: an
agent that cannot afford even the minimum price has to wait for credits.
Without this every agent would just bid its maximum.

The regeneration rates come from operator config, never from the agents:

    rate(agent) = pool * demand(agent) * weight(agent) / sum over agents of demand * weight

`demand` is how much work the agent is expected to send and `weight` is how much
the business values it; only their ratios matter, and the default of 1 for both
splits the pool equally. `pool` is the credits per second handed out across all
agents. The default of 10 is about one slice every 6 seconds (the experiment's
load) sold at about 60 credits, a typical price from the default scorer weights.
These are meant to be fixed before a run and swept between runs.

Balances live in memory and take the time as an argument. Not thread safe: the
gateway calls it only while holding its own lock.
"""

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    demand: float = 1.0  # expected load, in any unit shared by all agents
    weight: float = 1.0  # business importance, in any unit shared by all agents


class Budgets:
    def __init__(self, agents: dict[str, AgentConfig], start: float, pool: float = 10.0, cap_seconds: float = 60.0):
        """`cap_seconds` is how many seconds of regeneration an agent can bank."""
        shares = {name: a.demand * a.weight for name, a in agents.items()}
        if pool <= 0 or cap_seconds <= 0:
            raise ValueError("pool and cap_seconds must be positive")
        if any(s < 0 for s in shares.values()) or sum(shares.values()) <= 0:
            raise ValueError("demand and weight must not be negative, and at least one agent needs a share")
        total = sum(shares.values())
        self.rates = {name: pool * s / total for name, s in shares.items()}  # credits per second
        self._caps = {name: rate * cap_seconds for name, rate in self.rates.items()}
        self._balance = dict(self._caps)  # everyone starts full
        self._updated = {name: start for name in agents}
        self._held = dict.fromkeys(agents, 0.0)  # credits held by resting bids, per agent
        self._holds: dict[object, tuple[str, float]] = {}  # bid key -> (agent, held)

    def balance(self, agent: str, now: float) -> float:
        elapsed = max(0.0, now - self._updated[agent])
        self._balance[agent] = min(self._caps[agent], self._balance[agent] + self.rates[agent] * elapsed)
        self._updated[agent] = max(now, self._updated[agent])
        return self._balance[agent]

    def snapshot(self, now: float) -> dict[str, float]:
        """Every agent's balance now, for saving. Holds are left out on purpose: they belong to bids
        resting in a book that does not survive a restart, so the saved balance is what is really owned."""
        return {agent: self.balance(agent, now) for agent in self._balance}

    def restore(self, saved: dict[str, float], away: dict[str, float], now: float) -> None:
        """Start from balances saved earlier. `away[agent]` is the seconds since each was saved, during
        which it kept regenerating. Agents that were not saved start full, and saved agents that are no
        longer configured are ignored."""
        for agent, balance in saved.items():
            if agent in self._balance:
                self._balance[agent] = min(self._caps[agent], balance + self.rates[agent] * max(0.0, away.get(agent, 0.0)))
                self._updated[agent] = now

    def available(self, key, agent: str, now: float) -> int:
        """Whole credits `key` could hold now, counting the hold it already has as free.
        Zero if the agent's other bids already hold everything."""
        own = self._holds[key][1] if key in self._holds else 0.0
        return max(0, math.floor(self.balance(agent, now) - (self._held[agent] - own)))

    def seconds_until(self, key, agent: str, amount: int, now: float) -> float:
        """Seconds of regeneration until `key` could hold `amount`, if nothing else changes."""
        deficit = amount - self.available(key, agent, now)
        if deficit <= 0:
            return 0.0
        return deficit / self.rates[agent] if self.rates[agent] > 0 else math.inf

    def hold(self, key, agent: str, amount: float) -> None:
        """Hold `amount` for `key`, replacing any hold it has."""
        self.release(key)
        self._holds[key] = (agent, amount)
        self._held[agent] += amount

    def release(self, key) -> None:
        """Drop `key`'s hold without spending. A no-op if it has none."""
        if key in self._holds:
            agent, amount = self._holds.pop(key)
            self._held[agent] -= amount

    def settle(self, key, paid: float, now: float) -> None:
        """`key` won at `paid`, which is never more than its hold: release the hold and spend."""
        agent = self._holds[key][0]
        self.release(key)
        self._balance[agent] = max(0.0, self.balance(agent, now) - paid)  # the max only absorbs float error
