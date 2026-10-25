"""One event format and one writer for every gateway.

The experiment's metrics (completion time, P95, failures, wasted retries) are
computed from this log, so the FIFO, priority and exchange gateways must all
describe a request's life the same way. The shape is built in make_event and
nowhere else.

A request's life is:

    request, [bid, fill,] forward, [rejected, [bid, fill,] forward, ...], result
    request, ..., cancelled          (a caller withdrew it before it was sent)

`bid` and `fill` appear only on the exchange. `rejected` means the backend
answered a forward with a 429, which is one wasted retry.
"""

import json
import threading
from collections import defaultdict

KINDS = ("request", "bid", "fill", "forward", "rejected", "result", "cancelled")


def make_event(kind: str, gateway: str, task, t: float, **fields) -> dict:
    """`task` needs `request_id` and `attempts`. `t` is monotonic seconds."""
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}")
    return {"event": kind, "gateway": gateway, "request_id": task.request_id, "t": t, "attempt": task.attempts, **fields}


class EventLog:
    """Collects events in memory and, if given a path, appends them as JSON Lines.

    Gateways call it from several threads, so writes are serialized. Pass the
    instance as a gateway's `on_event`.
    """

    def __init__(self, path=None):
        self._lock = threading.Lock()
        self._events: list[dict] = []
        self._file = open(path, "a") if path else None

    def __call__(self, event: dict) -> None:
        with self._lock:
            self._events.append(event)
            if self._file:
                self._file.write(json.dumps(event) + "\n")
                self._file.flush()

    @property
    def events(self) -> list[dict]:
        with self._lock:
            return list(self._events)

    def close(self) -> None:
        with self._lock:
            if self._file:
                self._file.close()
                self._file = None

    def __enter__(self) -> "EventLog":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def check_lifecycle(events: list[dict]) -> list[str]:
    """Return the ways a log breaks the lifecycle above; an empty list means it is sound."""
    by_request: dict[str, list[dict]] = defaultdict(list)
    for e in events:
        by_request[e["request_id"]].append(e)

    problems = []
    for rid, evs in by_request.items():
        kinds = [e["event"] for e in evs]
        count = kinds.count
        if kinds[0] != "request" or count("request") != 1:
            problems.append(f"{rid}: must start with exactly one request")
        terminals = count("result") + count("cancelled")
        if terminals != 1 or kinds[-1] not in ("result", "cancelled"):
            problems.append(f"{rid}: must end with exactly one result or cancelled")
        if count("forward") != count("rejected") + count("result"):
            problems.append(f"{rid}: every forward must end in a rejected or a result")
        if count("fill") and count("fill") != count("forward"):
            problems.append(f"{rid}: every forward must follow one fill")
        if any(b["t"] < a["t"] for a, b in zip(evs, evs[1:])):
            problems.append(f"{rid}: time goes backwards")
    return problems
