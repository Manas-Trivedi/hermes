import threading
from contextlib import contextmanager

from experiments.mock_backend import MockBackend, make_server
from gateway import HttpSender


@contextmanager
def real_sender(backend_limit):
    """A sender wired to a real mock backend on a free port.

    The backend forgives 20ms of early arrival: each send is a fresh thread and
    connection, so two sends exactly one interval apart can arrive slightly closer.
    """
    backend = MockBackend(backend_limit, seed=1, median_latency=0.001, sigma=0.0, tolerance=0.02)
    server = make_server(backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield HttpSender(f"http://127.0.0.1:{server.server_port}/v1/complete")
    finally:
        server.shutdown()
        server.server_close()
