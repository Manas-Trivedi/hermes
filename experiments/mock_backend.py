"""Mock LLM backend: a seeded stand-in for the provider that is being throttled.

Two behaviours, both deterministic for a given seed:

  * Rate limit: accepted requests must be at least 60/limit seconds apart (the
    same spacing as one exchange slice). A request that arrives sooner gets a
    429 with a Retry-After header, and a rejected request does not move the
    window.
  * Latency: each request sleeps for a lognormal time (a typical value with a
    long slow tail, so P95 means something). The latency is derived from the
    seed and the request's own id, not from a shared random stream, so a
    gateway that sends requests in a different order still sees the same
    latency for each request.

The decision logic lives in MockBackend.handle(request_id, now), which takes the
time as an argument and never sleeps, so it can be tested without a server.
"""

import argparse
import json
import math
import random
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass(frozen=True)
class Response:
    status: int  # 200 or 429
    latency: float  # seconds the server should hold the response (0 for a 429)
    retry_after: float = 0.0  # seconds until a request would be accepted (429 only)


class MockBackend:
    def __init__(
        self,
        limit_per_minute: float,
        seed: int,
        median_latency: float = 2.0,
        sigma: float = 0.5,
        tolerance: float = 0.005,
    ):
        """`sigma` is the lognormal spread: larger means a heavier slow tail.

        `tolerance` forgives a request that arrives a hair early because of
        network jitter, so a gateway sending exactly on the slice boundary is
        not rejected for it. Set it to 0 for a strict limit.
        """
        if limit_per_minute <= 0 or median_latency <= 0 or sigma < 0 or tolerance < 0:
            raise ValueError("limit and median must be positive, sigma and tolerance non-negative")
        self.interval = 60.0 / limit_per_minute
        self._seed = seed
        self._mu = math.log(median_latency)
        self._sigma = sigma
        self._tolerance = tolerance
        self._last_accepted: float | None = None
        self._lock = threading.Lock()

    def latency_for(self, request_id: str) -> float:
        # A str seed is hashed by Random, so this is stable across processes.
        return random.Random(f"{self._seed}:{request_id}").lognormvariate(self._mu, self._sigma)

    def handle(self, request_id: str, now: float) -> Response:
        with self._lock:
            if self._last_accepted is not None:
                wait = self._last_accepted + self.interval - now
                if wait > self._tolerance:
                    return Response(429, 0.0, retry_after=wait)
            self._last_accepted = now
        return Response(200, self.latency_for(request_id))


def make_server(backend: MockBackend, port: int = 0, clock=time.monotonic) -> ThreadingHTTPServer:
    """POST /v1/complete with an X-Request-Id header. Port 0 picks a free port."""

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
            request_id = self.headers.get("X-Request-Id")
            if self.path != "/v1/complete" or not request_id:
                self._reply(400, {"error": "POST /v1/complete with X-Request-Id"})
                return
            r = backend.handle(request_id, clock())
            if r.status == 429:
                self._reply(429, {"error": "rate limited"}, {"Retry-After": f"{r.retry_after:.3f}"})
                return
            time.sleep(r.latency)
            self._reply(200, {"id": request_id, "latency": r.latency})

        def _reply(self, status, body, headers=None):
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass  # keep experiment output clean

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    p = argparse.ArgumentParser(description="Seeded mock LLM backend")
    p.add_argument("--limit", type=float, required=True, help="accepted requests per minute")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--median", type=float, default=2.0, help="median latency in seconds")
    p.add_argument("--sigma", type=float, default=0.5, help="lognormal spread (tail weight)")
    p.add_argument("--tolerance", type=float, default=0.005, help="early-arrival forgiveness in seconds")
    p.add_argument("--port", type=int, default=8000)
    a = p.parse_args()
    backend = MockBackend(a.limit, a.seed, a.median, a.sigma, a.tolerance)
    server = make_server(backend, a.port)
    print(f"mock backend on http://127.0.0.1:{server.server_port}/v1/complete")
    server.serve_forever()


if __name__ == "__main__":
    main()
