"""Live event feed over WebSocket.

EventFeed is passed to a gateway as its `on_event`, usually next to the event
writer. Every event goes out to every connected client as one JSON text
message, in the order the gateway emitted it, in the same shape as the event
log (gateway.events). A client sees only events from the time it connects; it
gets no history. Stored events are for history.

Gateways call it from their own threads and must never wait on a viewer. Each
client has a bounded queue. A client that falls behind by more than
`max_pending` events is dropped (closed with code 1013, "try again later")
instead of slowing the gateway or growing memory without bound.

With a `token`, a client must connect to `ws://host:port/?token=<token>` (a
browser cannot set headers on a WebSocket), or it is refused with a 401. The
feed carries every tenant's traffic, so anything but a local run should set one.
"""

import hmac
import json
import queue
import threading
from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

from websockets.protocol import State
from websockets.sync.server import serve

POLL = 0.5  # seconds between checks that a quiet client is still there


class EventFeed:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, max_pending: int = 1000, token: str | None = None):
        self._max_pending = max_pending
        self._token = token
        self._lock = threading.Lock()
        self._clients: set[queue.Queue] = set()
        self._server = serve(self._handle, host, port, process_request=self._authorize)
        self._thread = threading.Thread(target=self._server.serve_forever, name="event-feed", daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._server.socket.getsockname()[1]

    @property
    def clients(self) -> int:
        with self._lock:
            return len(self._clients)

    def __call__(self, event: dict) -> None:
        message = json.dumps(event)
        with self._lock:
            for q in list(self._clients):
                try:
                    q.put_nowait(message)
                except queue.Full:
                    self._clients.discard(q)  # its handler notices and closes the connection

    def close(self) -> None:
        self._server.shutdown()
        self._thread.join()

    def __enter__(self) -> "EventFeed":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _authorize(self, connection, request):
        if self._token is None:
            return None
        given = parse_qs(urlparse(request.path).query).get("token", [""])[0]
        if hmac.compare_digest(given.encode(), self._token.encode()):
            return None
        return connection.respond(HTTPStatus.UNAUTHORIZED, "missing or wrong feed token\n")

    def _handle(self, ws) -> None:
        q: queue.Queue = queue.Queue(self._max_pending)
        with self._lock:
            self._clients.add(q)
        try:
            while ws.protocol.state is State.OPEN:
                try:
                    message = q.get(timeout=POLL)
                except queue.Empty:
                    continue
                ws.send(message)
                with self._lock:
                    if q not in self._clients:
                        ws.close(1013, "too slow")
                        return
        finally:
            with self._lock:
                self._clients.discard(q)
