"""Sends tasks to the backend in the order its dispatcher chooses.

The dispatcher thread asks the dispatcher what is due and starts one short-lived
thread per request, because the backend's latency can be longer than the gap
between sends. A 429 puts the task back with the dispatcher and counts as a
wasted retry.
"""

import threading
import time

from experiments.baselines.dispatcher import RateLimitedDispatcher, Task
from gateway.events import make_event


class Gateway:
    def __init__(self, send, dispatcher: RateLimitedDispatcher, clock=time.monotonic, on_event=None):
        """`send(request_id)` returns a Reply. `on_event(dict)` sees every step (gateway.events)."""
        self._send = send
        self._clock = clock
        self._on_event = on_event or (lambda _: None)
        self._dispatcher = dispatcher
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

    def submit(self, request_id: str, priority: float = 0.0) -> Task:
        task = Task(request_id, priority)
        self._emit("request", task)
        with self._cv:
            self._dispatcher.submit(task, self._clock())
            self._cv.notify()
        return task

    def cancel(self, task: Task) -> bool:
        """Take a task out of the queue. False if it was already sent or is done."""
        with self._cv:
            if not self._dispatcher.cancel(task):
                return False
        task.cancelled = True
        self._emit("cancelled", task)
        task._done.set()
        return True

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
            self._emit("result", task, status=None, error=task.error)
            task._done.set()
            return
        if reply.status == 429:
            self._emit("rejected", task)  # before requeueing, so the retry's forward comes after it
            with self._cv:
                self.wasted_retries += 1
                self._dispatcher.retry(task, self._clock(), reply.retry_after)
                self._cv.notify()
            return
        task.status = reply.status
        self._emit("result", task, status=task.status, error=None)
        task._done.set()

    def _emit(self, event: str, task: Task, **fields) -> None:
        self._on_event(make_event(event, self._dispatcher.name, task, self._clock(), **fields))
