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

Aging: given `rescore(task, now)`, the gateway re-prices every resting bid each
`reprice_interval` seconds. A bid that scores higher than it offers is cancelled
and placed again at the new price, which gives it a new id and a later place in
the queue at that price. A bid is only ever raised, never lowered, so the price
a waiting task offers cannot fall.

Budgets: given `budgets` (pricing.Budgets), every task needs `meta.agent_id`. A
bid offers at most what its agent can afford. There is no overdraft: a task whose
agent cannot afford even the reserve price is not bid yet, and waits (still
cancellable) until credits come back. The bid holds its credits while it rests,
a win spends the price paid, and a cancel gives the hold back. A raise from aging is capped the same way. A call
the backend rejects with a 429 has already spent its credits, so its re-bid
spends again.

Tokens: given `tokens_per_minute`, a task carries an estimate of its tokens
(gateway.tokens), and every win is charged to the scheduler, which then holds
back the next slice until the tokens are repaid at that rate (scheduler.capacity).
"""

import threading
import time
from collections import deque
from dataclasses import dataclass

from client import Engine, Trade
from gateway.events import make_event
from scheduler import SLICE_ID_BASE, CapacityScheduler


class Task:
    def __init__(self, request_id: str, bid: int, meta=None, tokens: int = 0):
        self.request_id = request_id
        self.bid = bid  # price offered, in ticks; aging raises it
        self.meta = meta  # what the scorer needs to re-price the task (pricing.TaskMeta)
        self.tokens = tokens  # estimated tokens of the call, charged when it wins a slice
        self.paid: int | None = None  # price of the fill that won the latest slice
        self.attempts = 0  # calls sent to the backend
        self.cancelled = False
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
    def __init__(
        self, engine: Engine, limit_per_minute: float, start: float, reserve_price: int = 1, tokens_per_minute: float | None = None
    ):
        self._engine = engine
        self._scheduler = CapacityScheduler(
            engine, limit_per_minute, start=start, reserve_price=reserve_price, tokens_per_minute=tokens_per_minute
        )
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

    def resting(self) -> list[Task]:
        return list(self._resting.values())

    def reprice(self, task: Task, bid: int) -> list[Fill]:
        """Replace the task's bid with one at a new price (cancel and place again).
        It fills at once if an unsold slice is resting."""
        if bid < self._reserve:
            raise ValueError(f"bid {bid} is below the reserve price {self._reserve}")
        if not self.cancel(task):
            raise ValueError("task has no bid in the book")
        task.bid = bid
        return self.submit(task)

    def cancel(self, task: Task) -> bool:
        """Take the task's bid out of the book. False if it has no bid in the book,
        which means it already won and its call is on the way."""
        for bid_id, resting in self._resting.items():
            if resting is task:
                self._engine.cancel(bid_id)
                del self._resting[bid_id]
                return True
        return False

    def tick(self, now: float) -> list[Fill]:
        """Release and expire slices; returns the bids a new slice reached."""
        return self._fills(self._scheduler.tick(now).trades)

    def charge(self, fills: list[Fill], now: float) -> None:
        """Charge the wins' tokens to the scheduler. Call it right after the fills are seen."""
        for fill in fills:
            self._scheduler.charge(fill.task.tokens, now)

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
        rescore=None,
        reprice_interval: float = 1.0,
        budgets=None,
        tokens_per_minute: float | None = None,
    ):
        """`send(request_id)` returns a Reply. `on_event(dict)` sees every step (gateway.events).
        `rescore(task, now)` returns the price a resting task should offer now; see Aging above."""
        self._send = send
        self._clock = clock
        self._on_event = on_event or (lambda _: None)
        self._core = ExchangeCore(engine, limit_per_minute, start=clock(), reserve_price=reserve_price, tokens_per_minute=tokens_per_minute)
        self._rescore = rescore
        self._budgets = budgets
        self._reserve = reserve_price
        self._unfunded: list[Task] = []  # tasks waiting for their agent to afford the reserve price
        self._reprice_interval = reprice_interval
        self._next_reprice = clock() + reprice_interval
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

    def submit(self, request_id: str, bid: int, meta=None, tokens: int = 0) -> Task:
        task = Task(request_id, bid, meta, tokens)
        self._emit("request", task)
        with self._cv:
            self._inbox.append(task)
            self._cv.notify()
        return task

    def cancel(self, task: Task) -> bool:
        """Withdraw a task that has not won yet. False if it already won (the call
        is going out) or is done. The lock serializes this with the exchange thread,
        so a bid is either still in the book here or already filled."""
        with self._cv:
            if task in self._inbox:
                self._inbox.remove(task)
            elif task in self._unfunded:
                self._unfunded.remove(task)
            elif not self._core.cancel(task):
                return False
            if self._budgets:
                self._budgets.release(task)
        task.cancelled = True
        self._emit("cancelled", task)
        task._done.set()
        return True

    def _loop(self) -> None:
        with self._cv:
            while not self._stopped:
                fills = self._admit()
                fills += self._age()
                self._core.charge(fills, self._clock())  # before the tick, so a win here holds back this tick's slice
                ticked = self._core.tick(self._clock())
                self._core.charge(ticked, self._clock())
                fills += ticked
                for fill in fills:
                    fill.task.paid = fill.paid
                    if self._budgets:
                        self._budgets.settle(fill.task, fill.paid, self._clock())
                    self._emit("fill", fill.task, paid=fill.paid, offered=fill.task.bid)
                    threading.Thread(target=self._run, args=(fill.task,), daemon=True).start()
                if not self._inbox:
                    wake = self._core.next_deadline()
                    if self._rescore:
                        wake = min(wake, self._next_reprice)
                    now = self._clock()
                    for task in self._unfunded:
                        wake = min(wake, now + self._budgets.seconds_until(task, task.meta.agent_id, self._reserve, now))
                    self._cv.wait(max(0.0, wake - now))

    def _admit(self) -> list[Fill]:
        """Place the queued tasks that can be paid for; the rest wait, in arrival order."""
        fills = []
        while self._inbox:
            task = self._inbox.popleft()
            if self._budgets:
                self._unfunded.append(task)
            else:
                fills += self._place(task)
        waiting = []
        for task in self._unfunded:
            if self._affordable(task, task.bid) >= self._reserve:
                fills += self._place(task)
            else:
                waiting.append(task)
        self._unfunded = waiting
        return fills

    def _place(self, task: Task) -> list[Fill]:
        asked = task.bid
        if self._budgets:
            task.bid = self._affordable(task, asked)
            self._budgets.hold(task, task.meta.agent_id, task.bid)
        self._emit("bid", task, offered=task.bid, asked=asked)
        return self._core.submit(task)

    def _affordable(self, task: Task, bid: int) -> int:
        return min(bid, self._budgets.available(task, task.meta.agent_id, self._clock()))

    def _age(self) -> list[Fill]:
        """Raise the bids that score higher now, once every reprice interval."""
        now = self._clock()
        if not self._rescore or now < self._next_reprice:
            return []
        self._next_reprice = now + self._reprice_interval
        fills = []
        for task in self._core.resting():
            bid = self._rescore(task, now)
            if self._budgets:
                bid = self._affordable(task, bid)
            if bid > task.bid:
                if self._budgets:
                    self._budgets.hold(task, task.meta.agent_id, bid)
                self._emit("reprice", task, offered=bid, previous=task.bid)
                fills += self._core.reprice(task, bid)
        return fills

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
            self._emit("rejected", task)  # before requeueing, so the next bid comes after it
            with self._cv:
                self.wasted_retries += 1
                self._inbox.append(task)
                self._cv.notify()
            return
        task.status = reply.status
        self._emit("result", task, status=task.status, error=None)
        task._done.set()

    def _emit(self, event: str, task: Task, **fields) -> None:
        self._on_event(make_event(event, "exchange", task, self._clock(), **fields))
