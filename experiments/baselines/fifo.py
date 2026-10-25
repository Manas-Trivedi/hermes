"""Naive baseline: requests leave in arrival order.

This is the floor condition in the experiment. A request the backend rejects
with a 429 goes back to the front of the queue, so it does not lose its place.
"""

from collections import deque

from experiments.baselines.dispatcher import RateLimitedDispatcher, Task


class FifoDispatcher(RateLimitedDispatcher):
    def __init__(self, limit_per_minute: float):
        super().__init__(limit_per_minute)
        self._pending: deque[Task] = deque()

    def __len__(self) -> int:
        return len(self._pending)

    def cancel(self, task: Task) -> bool:
        try:
            self._pending.remove(task)
        except ValueError:
            return False
        return True

    def _enqueue(self, task: Task) -> None:
        self._pending.append(task)

    def _dequeue(self) -> Task:
        return self._pending.popleft()

    def _requeue(self, task: Task) -> None:
        self._pending.appendleft(task)
