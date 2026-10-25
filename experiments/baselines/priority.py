"""Priority scheduling with aging: the real baseline for the experiment.

The most urgent task goes first, and a task gains `aging_rate` points of
priority for every second it waits, so low priority work cannot starve behind a
stream of urgent work. The effective priority of a task at time t is

    priority + aging_rate * (t - enqueued_at)

Every task ages at the same rate, so two tasks always keep the same order
relative to each other however long they wait. Sorting by
priority - aging_rate * enqueued_at therefore gives the right order at any
time, and the heap key never has to be updated. Ties go to the earlier arrival.

The priority comes from the caller. Until the urgency scorer exists (D4) it is
whatever the caller declares, which is also the honest-agents case in the
experiment.
"""

import heapq
from itertools import count

from experiments.baselines.dispatcher import RateLimitedDispatcher, Task


class PriorityDispatcher(RateLimitedDispatcher):
    def __init__(self, limit_per_minute: float, aging_rate: float = 0.0):
        """`aging_rate` is priority points gained per second of waiting."""
        super().__init__(limit_per_minute)
        if aging_rate < 0:
            raise ValueError("aging rate must not be negative")
        self._aging_rate = aging_rate
        self._heap: list[tuple[float, int, Task]] = []
        self._seq = count()
        self._seqs: dict[int, int] = {}  # id(task) -> arrival number, kept across retries

    def __len__(self) -> int:
        return len(self._heap)

    def _push(self, task: Task) -> None:
        score = task.priority - self._aging_rate * task.enqueued_at
        heapq.heappush(self._heap, (-score, self._seqs[id(task)], task))

    def _enqueue(self, task: Task) -> None:
        self._seqs[id(task)] = next(self._seq)
        self._push(task)

    def _dequeue(self) -> Task:
        return heapq.heappop(self._heap)[2]

    def _requeue(self, task: Task) -> None:
        self._push(task)  # same score and arrival number, so the same place
