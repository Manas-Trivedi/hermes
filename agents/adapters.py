"""One way for an agent to submit a call, whichever gateway is behind it.

The three gateways take different arguments: the baselines take a priority, the
exchange takes a bid and the task's metadata. An adapter takes the metadata the
agent declares and prices it with the scorer, so the FIFO, priority and exchange
conditions run the same agents. The priority baseline and the exchange use the
same Scorer, so any gap between them comes from the mechanism and not from a
better price. FIFO ignores the price, so it needs no scorer.
"""

import time


class BaselineAdapter:
    """For the FIFO and priority gateways. Without a scorer every priority is 0."""

    def __init__(self, gateway, scorer=None, clock=time.monotonic):
        self._gateway = gateway
        self._scorer = scorer
        self._clock = clock

    def submit(self, request_id: str, meta):
        priority = self._scorer.score(meta, self._clock()).price if self._scorer else 0.0
        return self._gateway.submit(request_id, priority)

    def cancel(self, task) -> bool:
        return self._gateway.cancel(task)


class ExchangeAdapter:
    def __init__(self, gateway, scorer, clock=time.monotonic):
        self._gateway = gateway
        self._scorer = scorer
        self._clock = clock

    def submit(self, request_id: str, meta):
        return self._gateway.submit(request_id, self._scorer.score(meta, self._clock()).price, meta)

    def cancel(self, task) -> bool:
        return self._gateway.cancel(task)
