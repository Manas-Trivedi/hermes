import json
import time

import pytest
from websockets.sync.client import connect

from feed import EventFeed


def wait_for(condition, timeout=5):
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.005)


def event(i):
    return {"event": "bid", "gateway": "exchange", "request_id": f"r{i}", "t": float(i), "attempt": 0, "offered": i}


def test_every_connected_client_gets_every_event_in_order():
    with EventFeed() as feed:
        with connect(f"ws://127.0.0.1:{feed.port}") as a, connect(f"ws://127.0.0.1:{feed.port}") as b:
            wait_for(lambda: feed.clients == 2)
            for i in range(50):
                feed(event(i))
            for client in (a, b):
                assert [json.loads(client.recv(timeout=5)) for _ in range(50)] == [event(i) for i in range(50)]


def test_a_client_sees_only_events_from_after_it_connected():
    with EventFeed() as feed:
        feed(event(0))
        with connect(f"ws://127.0.0.1:{feed.port}") as client:
            wait_for(lambda: feed.clients == 1)
            feed(event(1))
            assert json.loads(client.recv(timeout=5)) == event(1)


def test_a_client_that_disconnects_is_forgotten_and_the_feed_keeps_serving():
    with EventFeed() as feed:
        with connect(f"ws://127.0.0.1:{feed.port}"):
            wait_for(lambda: feed.clients == 1)
        wait_for(lambda: feed.clients == 0)
        feed(event(0))  # no client: must not raise
        with connect(f"ws://127.0.0.1:{feed.port}") as client:
            wait_for(lambda: feed.clients == 1)
            feed(event(1))
            assert json.loads(client.recv(timeout=5)) == event(1)


def test_with_a_token_only_a_client_that_presents_it_is_let_in():
    from websockets.exceptions import InvalidStatus

    with EventFeed(token="s3cret") as feed:
        for url in (f"ws://127.0.0.1:{feed.port}", f"ws://127.0.0.1:{feed.port}/?token=wrong"):
            with pytest.raises(InvalidStatus) as refused:
                connect(url)
            assert refused.value.response.status_code == 401
        with connect(f"ws://127.0.0.1:{feed.port}/?token=s3cret") as client:
            wait_for(lambda: feed.clients == 1)
            feed(event(7))
            assert json.loads(client.recv(timeout=5)) == event(7)
