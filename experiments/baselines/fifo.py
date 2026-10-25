"""Naive gateway: a hard rate limit, a FIFO queue and retries on 429.

This is the floor condition in the experiment. Requests leave in arrival order,
at most one per 60/limit seconds. A request the backend rejects with a 429 goes
back to the front of the queue and waits out Retry-After, so it does not lose
its place. Every such rejection is a wasted retry.

FifoDispatcher holds all the ordering and timing and takes the time as an
argument, so it can be tested without sleeping. FifoGateway wraps it in a
dispatcher thread, plus one short-lived thread per request in flight, because
the backend's latency can be longer than the gap between sends.
"""

import threading
import time
from collections import deque


class Task:
    def __init__(self, request_id: str):
        self.request_id = request_id
        self.attempts = 0
        self.status: int | None = None  # final HTTP status once done
        self.error: str | None = None  # set if sending raised
        self._done = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)


class FifoDispatcher:
    def __init__(self, limit_per_minute: float):
        if limit_per_minute <= 0:
            raise ValueError("limit must be positive")
        self.interval = 60.0 / limit_per_minute
        self._pending: deque[Task] = deque()
        self._next_send = float("-inf")

    def submit(self, task: Task) -> None:
        self._pending.append(task)

    def pop_due(self, now: float) -> Task | None:
        """The head of the queue if a send is allowed at `now`; marks the send."""
        if not self._pending or now < self._next_send:
            return None
        self._next_send = now + self.interval
        return self._pending.popleft()

    def retry(self, task: Task, now: float, retry_after: float) -> None:
        """Put a rejected task back at the front and hold all sends for Retry-After."""
        self._pending.appendleft(task)
        self._next_send = max(self._next_send, now + retry_after)

    def wake_in(self, now: float) -> float | None:
        """Seconds until pop_due can return something, or None if the queue is empty."""
        if not self._pending:
            return None
        return max(0.0, self._next_send - now)


class FifoGateway:
    def __init__(self, send, limit_per_minute: float, clock=time.monotonic, on_event=None):
        """`send(request_id)` returns a Reply. `on_event(dict)` sees every step."""
        self._send = send
        self._clock = clock
        self._on_event = on_event or (lambda _: None)
        self._dispatcher = FifoDispatcher(limit_per_minute)
        self._cv = threading.Condition()
        self._stopped = False
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self.wasted_retries = 0

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *exc):
        with self._cv:
            self._stopped = True
            self._cv.notify()
        self._thread.join()

    def submit(self, request_id: str) -> Task:
        task = Task(request_id)
        self._emit("request", task)
        with self._cv:
            self._dispatcher.submit(task)
            self._cv.notify()
        return task

    def _loop(self) -> None:
        with self._cv:
            while not self._stopped:
                now = self._clock()
                task = self._dispatcher.pop_due(now)
                if task:
                    threading.Thread(target=self._run, args=(task,), daemon=True).start()
                else:
                    self._cv.wait(self._dispatcher.wake_in(now))

    def _run(self, task: Task) -> None:
        task.attempts += 1
        self._emit("forward", task)
        try:
            reply = self._send(task.request_id)
        except Exception as e:
            task.error = repr(e)
            self._emit("result", task)
            task._done.set()
            return
        if reply.status == 429:
            with self._cv:
                self.wasted_retries += 1
                self._dispatcher.retry(task, self._clock(), reply.retry_after)
                self._cv.notify()
            self._emit("rejected", task)
            return
        task.status = reply.status
        self._emit("result", task)
        task._done.set()

    def _emit(self, event: str, task: Task) -> None:
        self._on_event({"event": event, "request_id": task.request_id, "t": self._clock()})
