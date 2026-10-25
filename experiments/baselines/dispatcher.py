"""Rate limiting and retry timing shared by every baseline gateway.

A dispatcher decides which queued task is sent next and when. The when is the
same for all of them: at most one send per 60/limit seconds, and a 429 holds
every send for its Retry-After. Only the order differs, so subclasses supply
the queue (_enqueue, _dequeue, _requeue, __len__).

Everything takes the time as an argument, so it can be tested without sleeping.
"""

import threading


class Task:
    def __init__(self, request_id: str, priority: float = 0.0):
        self.request_id = request_id
        self.priority = priority  # higher is more urgent; FIFO ignores it
        self.enqueued_at = 0.0
        self.seq = 0  # arrival number, assigned by a dispatcher that needs one
        self.attempts = 0
        self.cancelled = False
        self.status: int | None = None  # final HTTP status once done
        self.error: str | None = None  # set if sending raised
        self._done = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)


class RateLimitedDispatcher:
    name = "baseline"  # labels this dispatcher's gateway in the event log

    def __init__(self, limit_per_minute: float):
        if limit_per_minute <= 0:
            raise ValueError("limit must be positive")
        self.interval = 60.0 / limit_per_minute
        self._next_send = float("-inf")

    def submit(self, task: Task, now: float) -> None:
        task.enqueued_at = now
        self._enqueue(task)

    def pop_due(self, now: float) -> Task | None:
        """The next task if a send is allowed at `now`; marks the send."""
        if not len(self) or now < self._next_send:
            return None
        self._next_send = now + self.interval
        return self._dequeue()

    def retry(self, task: Task, now: float, retry_after: float) -> None:
        """Put a rejected task back with its place kept, and hold all sends for Retry-After."""
        self._requeue(task)
        self._next_send = max(self._next_send, now + retry_after)

    def wake_in(self, now: float) -> float | None:
        """Seconds until pop_due can return something, or None if the queue is empty."""
        if not len(self):
            return None
        return max(0.0, self._next_send - now)

    def cancel(self, task: Task) -> bool:
        """Remove a queued task. False if it is not queued (already sent, or cancelled)."""
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError

    def _enqueue(self, task: Task) -> None:
        raise NotImplementedError

    def _dequeue(self) -> Task:
        raise NotImplementedError

    def _requeue(self, task: Task) -> None:
        raise NotImplementedError
