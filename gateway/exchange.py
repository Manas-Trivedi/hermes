"""Exchange gateway: a call is forwarded only after its bid has won a slice.

A task arrives with a bid price. The bid rests in the book until a slice
reaches it, and only then is the call sent to the backend. A slice reaches a
bid in one of two ways: a slice released into a book that already holds the bid
(the slice is the taker, and the trade is at the bid's price), or a bid placed
while an unsold slice is resting (the bid is the taker, and it pays the
slice's reserve price).

ExchangeCore holds the market logic and takes the time as an argument, so it
can be tested without sleeping. ExchangeGateway runs it on one thread, which
owns the Engine as the Engine requires, and sends each winning call on a
short-lived thread of its own, because the backend's latency can be longer than
the gap between slices.

If the backend rejects a call that already won a slice (the slice is spent),
the task is bid again at the same price under a new id, and that counts as a
wasted retry.
"""

import threading
import time
from collections import deque
from dataclasses import dataclass

from client import Engine, Trade
from scheduler import SLICE_ID_BASE, CapacityScheduler


class Task:
    def __init__(self, request_id: str, bid: int):
        self.request_id = request_id
        self.bid = bid  # price offered, in ticks
        self.paid: int | None = None  # price of the fill that won the latest slice
        self.attempts = 0  # calls sent to the backend
        self.status: int | None = None  # final HTTP status once done
        self.error: str | None = None  # set if sending raised
        self._done = threading.Event()

    def wait(self, timeout: float | None = None) -> bool:
        return self._done.wait(timeout)


@dataclass(frozen=True)
class Fill:
    task: Task
    paid: int  # trade price: the bid's own price, or the reserve for a late bid


class ExchangeCore:
    def __init__(self, engine: Engine, limit_per_minute: float, start: float, reserve_price: int = 1):
        self._engine = engine
        self._scheduler = CapacityScheduler(engine, limit_per_minute, start=start, reserve_price=reserve_price)
        self._reserve = reserve_price
        self._next_bid_id = 1
        self._resting: dict[int, Task] = {}  # bid id -> task, for bids still in the book

    def next_deadline(self) -> float:
        return self._scheduler.next_deadline()

    def submit(self, task: Task) -> list[Fill]:
        """Place a bid. It fills at once if an unsold slice is resting. A task
        bid again after a fill gets a fresh id each time."""
        if task.bid < self._reserve:
            raise ValueError(f"bid {task.bid} is below the reserve price {self._reserve}")
        bid_id = self._next_bid_id
        self._next_bid_id += 1
        self._resting[bid_id] = task
        return self._fills(self._engine.buy(bid_id, task.bid, 1))

    def tick(self, now: float) -> list[Fill]:
        """Release and expire slices; returns the bids a new slice reached."""
        return self._fills(self._scheduler.tick(now).trades)

    def _fills(self, trades: list[Trade]) -> list[Fill]:
        fills = []
        for t in trades:
            bid_id = t.taker_id if t.taker_id < SLICE_ID_BASE else t.maker_id
            fills.append(Fill(self._resting.pop(bid_id), t.price))
        return fills


class ExchangeGateway:
    def __init__(
        self,
        send,
        engine: Engine,
        limit_per_minute: float,
        clock=time.monotonic,
        on_event=None,
        reserve_price: int = 1,
    ):
        """`send(request_id)` returns a Reply. `on_event(dict)` sees every step."""
        self._send = send
        self._clock = clock
        self._on_event = on_event or (lambda _: None)
        self._core = ExchangeCore(engine, limit_per_minute, start=clock(), reserve_price=reserve_price)
        self._cv = threading.Condition()
        self._inbox: deque[Task] = deque()  # bids waiting to be placed by the exchange thread
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

    def submit(self, request_id: str, bid: int) -> Task:
        task = Task(request_id, bid)
        self._emit("request", task)
        with self._cv:
            self._inbox.append(task)
            self._cv.notify()
        return task

    def _loop(self) -> None:
        with self._cv:
            while not self._stopped:
                fills = []
                while self._inbox:
                    task = self._inbox.popleft()
                    self._emit("bid", task, offered=task.bid)
                    fills += self._core.submit(task)
                fills += self._core.tick(self._clock())
                for fill in fills:
                    fill.task.paid = fill.paid
                    self._emit("fill", fill.task, paid=fill.paid, offered=fill.task.bid)
                    threading.Thread(target=self._run, args=(fill.task,), daemon=True).start()
                if not self._inbox:
                    self._cv.wait(max(0.0, self._core.next_deadline() - self._clock()))

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
                self._inbox.append(task)
                self._cv.notify()
            self._emit("rejected", task)
            return
        task.status = reply.status
        self._emit("result", task)
        task._done.set()

    def _emit(self, event: str, task: Task, **fields) -> None:
        self._on_event({"event": event, "request_id": task.request_id, "t": self._clock(), **fields})
