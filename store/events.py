"""Storing the shared event log (gateway.events) in Postgres.

EventWriter is passed to a gateway as its `on_event`. Gateways call it from
their own threads and must not wait on the database, so it only queues the
event; one background thread, with its own connection, writes the queue in
batches and spreads each event over the tables in schema.sql.

A database failure stops the writer. It does not retry, and it does not raise
inside the gateway. `close()` raises the error instead, so a run cannot report
"done" while its events were lost. Always close the writer, or use it as a
context manager.
"""

import json
import queue
import threading

from store.db import connect

_STOP = object()
BATCH = 500

_INSERT_REQUEST = "INSERT INTO requests (run_id, request_id, gateway, tenant_id, t_request) VALUES (%s, %s, %s, %s, %s)"
_INSERT_ORDER = (
    "INSERT INTO orders (run_id, request_id, attempt, kind, offered, asked, previous, t)"
    " VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
)
_INSERT_FILL = "INSERT INTO fills (run_id, request_id, attempt, paid, offered, t) VALUES (%s, %s, %s, %s, %s, %s)"
_COUNT = "UPDATE requests SET {col} = {col} + 1 WHERE run_id = %s AND request_id = %s"
_END = (
    "UPDATE requests SET outcome = %s, t_end = %s, status = %s, error = %s WHERE run_id = %s AND request_id = %s"
)


def create_run(conn, name: str, condition: str, seed: int | None = None, params: dict | None = None) -> int:
    """Start an experiment run and return its id."""
    row = conn.execute(
        "INSERT INTO experiment_runs (name, condition, seed, params) VALUES (%s, %s, %s, %s) RETURNING id",
        (name, condition, seed, json.dumps(params or {})),
    ).fetchone()
    conn.commit()
    return row[0]


def finish_run(conn, run_id: int) -> None:
    conn.execute("UPDATE experiment_runs SET finished_at = now() WHERE id = %s", (run_id,))
    conn.commit()


class EventWriter:
    def __init__(self, url: str, run_id: int):
        self._run_id = run_id
        self._queue: queue.Queue = queue.Queue()
        self._error: BaseException | None = None
        self._conn = connect(url)
        self._thread = threading.Thread(target=self._run, name="event-writer", daemon=True)
        self._thread.start()

    def __call__(self, event: dict) -> None:
        if not self._error:  # the writer is dead; do not pile up events nobody will write
            self._queue.put(event)

    def close(self) -> None:
        """Write what is queued, stop, and raise if any write failed."""
        if self._thread.is_alive():
            self._queue.put(_STOP)
            self._thread.join()
        self._conn.close()
        if self._error:
            raise RuntimeError("event writer failed; events were lost") from self._error

    def __enter__(self) -> "EventWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _run(self) -> None:
        stopping = False
        while not stopping:
            batch = [self._queue.get()]
            while len(batch) < BATCH and not self._queue.empty():
                batch.append(self._queue.get_nowait())
            if batch[-1] is _STOP:
                stopping = True
                batch.pop()
            try:
                with self._conn.transaction():
                    for event in batch:
                        self._write(event)
            except BaseException as e:
                self._error = e
                return

    def _write(self, e: dict) -> None:
        run, rid, kind = self._run_id, e["request_id"], e["event"]
        execute = self._conn.execute
        update = self._update
        if kind == "request":
            execute(_INSERT_REQUEST, (run, rid, e["gateway"], e.get("tenant_id"), e["t"]))
        elif kind in ("bid", "reprice"):
            execute(_INSERT_ORDER, (run, rid, e["attempt"], kind, e["offered"], e.get("asked"), e.get("previous"), e["t"]))
        elif kind == "fill":
            execute(_INSERT_FILL, (run, rid, e["attempt"], e["paid"], e["offered"], e["t"]))
        elif kind == "forward":
            update(_COUNT.format(col="forwards"), (run, rid))
        elif kind == "rejected":
            update(_COUNT.format(col="rejections"), (run, rid))
        elif kind == "result":
            update(_END, ("result", e["t"], e["status"], e["error"], run, rid))
        elif kind == "cancelled":
            update(_END, ("cancelled", e["t"], None, None, run, rid))

    def _update(self, sql: str, args: tuple) -> None:
        if self._conn.execute(sql, args).rowcount != 1:
            raise LookupError(f"event for an unknown request: {args[-1]!r}")
