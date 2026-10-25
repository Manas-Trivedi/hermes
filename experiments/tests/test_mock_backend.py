import json
import threading
import urllib.error
import urllib.request

from experiments.mock_backend import MockBackend, make_server


def backend(**kw) -> MockBackend:
    kw.setdefault("limit_per_minute", 10)  # one accepted request per 6 seconds
    kw.setdefault("seed", 1)
    kw.setdefault("tolerance", 0.0)
    return MockBackend(**kw)


def test_latency_depends_on_seed_and_id_but_not_on_request_order():
    ids = [f"r{i}" for i in range(20)]
    a, b = backend(), backend()
    forward = {i: a.latency_for(i) for i in ids}
    backward = {i: b.latency_for(i) for i in reversed(ids)}
    assert forward == backward
    assert forward != {i: backend(seed=2).latency_for(i) for i in ids}


def test_latency_has_the_configured_median_and_a_slow_tail():
    b = backend(median_latency=2.0, sigma=0.5)
    xs = sorted(b.latency_for(f"r{i}") for i in range(4000))
    median, p95 = xs[len(xs) // 2], xs[int(len(xs) * 0.95)]
    assert 1.9 < median < 2.1
    assert p95 > 1.8 * median  # exp(1.645 * 0.5) is about 2.3


def test_requests_closer_than_the_interval_get_429_and_do_not_move_the_window():
    b = backend()
    assert b.handle("a", 100.0).status == 200
    early = b.handle("b", 102.0)
    assert early.status == 429 and abs(early.retry_after - 4.0) < 1e-9
    assert b.handle("c", 105.9).status == 429  # the rejected "b" did not restart the clock
    assert b.handle("d", 106.0).status == 200


def test_tolerance_forgives_a_hair_early_but_not_more():
    b = backend(tolerance=0.01)
    b.handle("a", 100.0)
    assert b.handle("b", 105.995).status == 200
    assert b.handle("c", 111.9).status == 429  # 5.905 after "b", beyond tolerance


def test_http_round_trip_returns_200_then_429_with_retry_after():
    server = make_server(backend(median_latency=0.001, sigma=0.0))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_port}/v1/complete"

    def post(request_id):
        req = urllib.request.Request(url, data=b"{}", method="POST", headers={"X-Request-Id": request_id})
        return urllib.request.urlopen(req)

    try:
        with post("a") as r:
            assert r.status == 200 and json.load(r)["id"] == "a"
        try:
            post("b")
            raise AssertionError("expected a 429")
        except urllib.error.HTTPError as e:
            assert e.code == 429 and float(e.headers["Retry-After"]) > 0
    finally:
        server.shutdown()
        server.server_close()
