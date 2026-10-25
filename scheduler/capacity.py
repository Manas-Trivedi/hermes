"""Capacity scheduler: sells the throttle rate into the book, one slice at a time.

A slice is a SELL of quantity 1 at the reserve price. It hits the highest
resting bid; if there is none it rests until it expires and is cancelled.

All logic lives in tick(now), which takes the current time as an argument so it
can be driven without sleeping. The caller owns the loop and the Engine: the
Engine is not thread safe, so tick() must run on the thread that uses it.
"""

from dataclasses import dataclass, field

from client import Engine, Trade, UnknownId

# Bidders use ids below this; slices count up from here (see engine/PROTOCOL.md).
SLICE_ID_BASE = 2**32


@dataclass(frozen=True)
class TickResult:
    released: list[int] = field(default_factory=list)  # slice ids put on sale
    expired: list[int] = field(default_factory=list)  # slice ids cancelled unsold
    # Trades from the released slice hitting resting bids. The slice is the
    # taker and the winning bid is the maker.
    trades: list[Trade] = field(default_factory=list)


class CapacityScheduler:
    def __init__(
        self,
        engine: Engine,
        limit_per_minute: float,
        start: float,
        reserve_price: int = 1,
        burst: int = 1,
    ):
        """Release one slice every 60/limit seconds, the first at `start`.

        A slice lives `burst` intervals. With burst=1 at most one slice is open
        and the rate is strict; a larger burst lets unsold capacity carry over,
        so up to `burst` slices can be sold back to back after an idle spell.
        """
        if limit_per_minute <= 0 or burst < 1 or reserve_price < 1:
            raise ValueError("limit must be positive, burst and reserve at least 1")
        self._engine = engine
        self.interval = 60.0 / limit_per_minute
        self._reserve = reserve_price
        self._ttl = burst * self.interval
        self._next_release = start
        self._next_id = SLICE_ID_BASE
        self._open: list[tuple[int, float]] = []  # (slice id, expires at), oldest first

    def next_deadline(self) -> float:
        """The earliest time tick() has anything to do."""
        if self._open:
            return min(self._next_release, self._open[0][1])
        return self._next_release

    def tick(self, now: float) -> TickResult:
        result = TickResult()
        # Expire before releasing, so at an exact boundary the old slice is
        # cancelled first and the new one replaces it.
        while self._open and self._open[0][1] <= now:
            slice_id, _ = self._open.pop(0)
            try:
                self._engine.cancel(slice_id)
                result.expired.append(slice_id)
            except UnknownId:
                pass  # sold to a bid that arrived after it was released
        if now >= self._next_release:
            self._release(now, result)
            # Capacity not sold in a window is gone: skip any missed releases
            # instead of firing them all at once after a late tick.
            missed = int((now - self._next_release) // self.interval) + 1
            self._next_release += missed * self.interval
        return result

    def _release(self, now: float, result: TickResult) -> None:
        slice_id = self._next_id
        self._next_id += 1
        trades = self._engine.sell(slice_id, self._reserve, 1)
        result.released.append(slice_id)
        result.trades.extend(trades)
        if not trades:  # a quantity-1 slice that traded is gone
            self._open.append((slice_id, now + self._ttl))
