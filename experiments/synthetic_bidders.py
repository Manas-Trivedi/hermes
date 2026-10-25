"""Runs the exchange end to end with random bidders, to check the market works.

One thread owns the engine and the scheduler, as the Engine requires. Each
iteration ticks the scheduler, submits the bids that have arrived, then sleeps
until the next thing is due. Invariants are checked at the end and the run
fails loudly if any is broken.

    uv run python -m experiments.synthetic_bidders --duration 10 --limit 30
"""

import argparse
import random
import time
from dataclasses import dataclass
from typing import Callable

from client import Engine, Trade
from scheduler import SLICE_ID_BASE, CapacityScheduler


class InvariantError(Exception):
    pass


@dataclass
class Summary:
    released: int = 0
    sold: int = 0  # slices that found a bid
    sold_on_release: int = 0  # slice hit a bid that was already resting
    sold_late: int = 0  # bid arrived and took a resting slice, at the slice's price
    expired: int = 0  # cancelled unsold at expiry
    open_at_end: int = 0  # still unsold when the run ended
    bids: int = 0
    bids_unfilled: int = 0  # still resting when the run ended


def run(
    duration: float,
    limit: float,
    bid_rate: float,
    seed: int,
    burst: int = 1,
    max_price: int = 100,
    arena: int = 10_000,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    out: Callable[[str], None] = print,
) -> Summary:
    rng = random.Random(seed)
    summary = Summary()
    slices: set[int] = set()
    bids: dict[int, int] = {}  # bid id -> price offered

    start = clock()
    end = start + duration
    next_bid_at = start + rng.expovariate(bid_rate)

    def log(now: float, text: str) -> None:
        out(f"t={now - start:6.2f}s  {text}")

    def record(now: float, trades: list[Trade]) -> None:
        for t in trades:
            taker_is_slice = t.taker_id >= SLICE_ID_BASE
            slice_id, bid_id = (t.taker_id, t.maker_id) if taker_is_slice else (t.maker_id, t.taker_id)
            if slice_id not in slices or bid_id not in bids or bid_id >= SLICE_ID_BASE:
                raise InvariantError(f"trade between unknown orders: {t}")
            summary.sold += 1
            if taker_is_slice:
                summary.sold_on_release += 1
                note = f"slice {slice_id - SLICE_ID_BASE} hit bid {bid_id}"
            else:
                summary.sold_late += 1
                note = f"bid {bid_id} took resting slice {slice_id - SLICE_ID_BASE} (pays reserve)"
            log(now, f"FILL    {note}: offered {bids[bid_id]}, paid {t.price}")

    with Engine(arena=arena) as engine:
        sched = CapacityScheduler(engine, limit, start=start, burst=burst)
        while True:
            now = clock()
            if now >= end:
                break

            result = sched.tick(now)
            for slice_id in result.released:
                slices.add(slice_id)
                summary.released += 1
                log(now, f"RELEASE slice {slice_id - SLICE_ID_BASE}")
            for slice_id in result.expired:
                summary.expired += 1
                log(now, f"EXPIRE  slice {slice_id - SLICE_ID_BASE} unsold")
            record(now, result.trades)

            while next_bid_at <= now:
                bid_id = len(bids) + 1
                price = rng.randint(1, max_price)
                bids[bid_id] = price
                summary.bids += 1
                log(now, f"BID     {bid_id} at {price}")
                record(now, engine.buy(bid_id, price, 1))
                next_bid_at += rng.expovariate(bid_rate)

            wake = min(sched.next_deadline(), next_bid_at, end)
            sleep(max(0.0, wake - clock()))

        # Cleanup: whatever is left in the book is cancelled, then it must be empty.
        for entry in engine.book():
            engine.cancel(entry.id)
            if entry.id >= SLICE_ID_BASE:
                summary.open_at_end += 1
            else:
                summary.bids_unfilled += 1
        if engine.book():
            raise InvariantError("book not empty after cleanup")

    if summary.released != summary.sold + summary.expired + summary.open_at_end:
        raise InvariantError(f"slices do not add up: {summary}")
    if summary.bids != summary.sold + summary.bids_unfilled:
        raise InvariantError(f"bids do not add up: {summary}")
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--duration", type=float, default=10, help="seconds to run")
    p.add_argument("--limit", type=float, default=30, help="slices released per minute")
    p.add_argument("--bid-rate", type=float, default=1.0, help="average bids per second")
    p.add_argument("--burst", type=int, default=1, help="intervals a slice lives")
    p.add_argument("--max-price", type=int, default=100)
    p.add_argument("--seed", type=int, default=0)
    a = p.parse_args()
    s = run(a.duration, a.limit, a.bid_rate, a.seed, a.burst, a.max_price)
    print(f"\n{s}")
    print("invariants held")


if __name__ == "__main__":
    main()
