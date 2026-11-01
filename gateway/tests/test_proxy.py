import asyncio
import json
import os
import time
from contextlib import asynccontextmanager

import aiohttp
import pytest
from aiohttp import web

from client import Engine
from client.engine import DEFAULT_BINARY
from gateway.proxy import CHAT_PATH, RUNNER_ARGS, Proxy
from store import create_run
from store.tests.helpers import temp_schema

BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
pytestmark = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")

CHAT = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4}


async def serve(app: web.Application, **runner_args) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app, **runner_args)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


@asynccontextmanager
async def running(handler, limit=600, holder=None, **proxy_args):
    """A fake provider running `handler`, a proxy in front of it, and a client session.
    A test that needs the Proxy itself passes a dict as `holder` and finds it under "proxy"."""
    upstream, upstream_url = await serve(_app(handler))
    with Engine(arena=1000) as engine:
        proxy = Proxy(upstream_url + CHAT_PATH, engine, limit, **proxy_args)
        if holder is not None:
            holder["proxy"] = proxy
        front, front_url = await serve(proxy.app(), **RUNNER_ARGS)
        try:
            async with aiohttp.ClientSession() as client:
                yield client, front_url + CHAT_PATH
        finally:
            await front.cleanup()
            await upstream.cleanup()


def _app(handler) -> web.Application:
    app = web.Application()
    app.router.add_post(CHAT_PATH, handler)
    return app


def run(scenario):
    asyncio.run(asyncio.wait_for(scenario(), 20))


def test_a_reply_comes_back_byte_for_byte_with_its_status_and_headers():
    async def provider(request):
        assert json.loads(await request.read()) == CHAT and request.headers["Authorization"] == "Bearer k"
        return web.Response(body=b'{"id":"x","choices":[]}', status=201, headers={"X-Ratelimit": "9", "Content-Type": "application/json"})

    async def scenario():
        async with running(provider) as (client, url):
            async with client.post(url, json=CHAT, headers={"Authorization": "Bearer k"}) as r:
                assert (r.status, r.headers["X-Ratelimit"], await r.read()) == (201, "9", b'{"id":"x","choices":[]}')

    run(scenario)


def test_a_stream_reaches_the_client_chunk_by_chunk_while_the_provider_is_still_sending():
    async def scenario():
        seen = asyncio.Event()

        async def provider(request):
            reply = web.StreamResponse(headers={"Content-Type": "text/event-stream"})
            await reply.prepare(request)
            await reply.write(b"data: one\n\n")
            await seen.wait()  # the provider will not send the rest until the client has the first chunk
            await reply.write(b"data: two\n\n")
            await reply.write_eof()
            return reply

        async with running(provider) as (client, url):
            async with client.post(url, json={**CHAT, "stream": True}) as r:
                chunks = []
                async for chunk in r.content.iter_any():
                    chunks.append(chunk)
                    seen.set()
                assert b"".join(chunks) == b"data: one\n\ndata: two\n\n" and chunks[0].startswith(b"data: one")

    run(scenario)


def test_a_429_from_the_provider_is_retried_and_the_client_only_sees_the_success():
    calls = []

    async def provider(request):
        calls.append(time.monotonic())
        return web.Response(status=429, headers={"Retry-After": "0"}) if len(calls) == 1 else web.json_response({"ok": True})

    async def scenario():
        async with running(provider) as (client, url):
            async with client.post(url, json=CHAT) as r:
                assert (r.status, await r.json()) == (200, {"ok": True}) and len(calls) == 2

    run(scenario)


def test_waiting_calls_leave_in_urgency_order_not_arrival_order():
    order = []

    async def provider(request):
        order.append(request.headers.get("X-Test-Name"))
        return web.json_response({})

    async def scenario():
        async with running(provider, limit=120) as (client, url):  # a slice every 0.5s
            async def call(name, headers):
                async with client.post(url, json=CHAT, headers={"X-Test-Name": name, **headers}) as r:
                    assert r.status == 200

            await call("first", {})  # takes the slice resting at start, so the next three queue behind a clock
            waiting = [
                asyncio.create_task(call("batch", {"X-Hermes-Batch": "b1"})),
                asyncio.create_task(call("plain", {})),
                asyncio.create_task(call("urgent", {"X-Hermes-User-Facing": "true", "X-Hermes-Deadline-Seconds": "1"})),
            ]
            await asyncio.gather(*waiting)
        assert order == ["first", "urgent", "plain", "batch"]

    run(scenario)


def test_the_estimated_tokens_space_out_calls_and_urgency_headers_never_reach_the_provider():
    arrived = []

    async def provider(request):
        assert not [h for h in request.headers if h.lower().startswith("x-hermes")]
        arrived.append(time.monotonic())
        return web.json_response({})

    async def scenario():
        async with running(provider, limit=6000, tokens_per_minute=300) as (client, url):  # 5 tokens a second
            body = {**CHAT, "messages": [{"role": "user", "content": ""}], "max_tokens": 3}  # 3 tokens: 0.6s apart
            for _ in range(3):
                async with client.post(url, json=body, headers={"X-Hermes-Batch": "b"}) as r:
                    assert r.status == 200
        assert all(b - a >= 0.55 for a, b in zip(arrived, arrived[1:]))

    run(scenario)


@pytest.mark.parametrize("body, headers", [
    (b"{not json", {}),
    (b'{"model": "m"}', {}),
    (json.dumps({**CHAT, "max_tokens": "lots"}).encode(), {}),
    (json.dumps(CHAT).encode(), {"X-Hermes-Deadline-Seconds": "soon"}),
    (json.dumps(CHAT).encode(), {"X-Hermes-User-Facing": "maybe"}),
])
def test_a_request_that_cannot_be_priced_is_refused_before_it_bids(body, headers):
    calls = []

    async def provider(request):
        calls.append(1)
        return web.json_response({})

    async def scenario():
        async with running(provider) as (client, url):
            async with client.post(url, data=body, headers=headers) as r:
                assert r.status == 400 and (await r.json())["error"]["type"] == "invalid_request_error"
        assert calls == []

    run(scenario)


def test_a_provider_that_is_down_gives_a_502_in_the_openai_error_shape():
    async def scenario():
        with Engine(arena=100) as engine:
            front, url = await serve(Proxy("http://127.0.0.1:1/v1/chat/completions", engine, 600).app(), **RUNNER_ARGS)
            try:
                async with aiohttp.ClientSession() as client:
                    async with client.post(url + CHAT_PATH, json=CHAT) as r:
                        assert r.status == 502 and (await r.json())["error"]["type"] == "api_connection_error"
            finally:
                await front.cleanup()

    run(scenario)


def tenants(*specs):
    """The `keys` a Proxy takes, from (tenant id, share, api key) triples."""
    from gateway.config import Tenant, hash_key

    return {hash_key(key): Tenant(name, share) for name, share, key in specs}


def test_with_tenants_a_missing_or_unknown_key_is_refused_and_the_provider_sees_its_own_key_never_the_clients():
    seen = []

    async def provider(request):
        seen.append(request.headers["Authorization"])
        return web.json_response({})

    async def scenario():
        async with running(provider, keys=tenants(("acme", 1, "k1")), upstream_key="sk-provider") as (client, url):
            for headers in ({}, {"Authorization": "Bearer nope"}, {"Authorization": "k1"}):
                async with client.post(url, json=CHAT, headers=headers) as r:
                    assert r.status == 401 and (await r.json())["error"]["type"] == "invalid_request_error"
            assert seen == []
            async with client.post(url, json=CHAT, headers={"Authorization": "Bearer k1"}) as r:
                assert r.status == 200
        assert seen == ["Bearer sk-provider"]

    run(scenario)


def test_every_event_of_a_request_carries_its_tenant_and_budgets_are_per_tenant():
    events = []
    urgent = {"X-Hermes-User-Facing": "true", "X-Hermes-Deadline-Seconds": "1"}  # priced at about 90

    async def provider(request):
        return web.json_response({})

    async def scenario():
        keys = tenants(("small", 1, "ks"), ("big", 9, "kb"))
        async with running(provider, keys=keys, pool=10, on_event=events.append) as (client, url):  # caps: 60 and 540 credits
            for key in ("ks", "kb"):
                async with client.post(url, json=CHAT, headers={"Authorization": f"Bearer {key}", **urgent}) as r:
                    assert r.status == 200
        by_tenant = {}
        for e in events:
            by_tenant.setdefault(e["tenant_id"], []).append(e)
        assert set(by_tenant) == {"small", "big"} and sum(len(v) for v in by_tenant.values()) == len(events)
        bids = {t: next(e for e in evs if e["event"] == "bid") for t, evs in by_tenant.items()}
        assert bids["small"]["offered"] == 60 < bids["small"]["asked"]  # held to its own balance
        assert bids["big"]["offered"] == bids["big"]["asked"]  # the other tenant's balance is untouched

    run(scenario)


async def until(condition, seconds=3.0):
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting"
        await asyncio.sleep(0.02)


def test_a_client_that_hangs_up_while_waiting_has_its_bid_withdrawn_and_nothing_is_sent():
    events, calls = [], []

    async def provider(request):
        calls.append(1)
        return web.json_response({})

    async def scenario():
        async with running(provider, limit=6, on_event=events.append) as (client, url):  # a slice every 10s
            async with client.post(url, json=CHAT) as r:  # takes the slice resting at start
                assert r.status == 200
            with pytest.raises(asyncio.TimeoutError):
                async with client.post(url, json=CHAT, timeout=aiohttp.ClientTimeout(total=0.3)):
                    pass
            await until(lambda: any(e["event"] == "cancelled" for e in events))
        assert len(calls) == 1

    run(scenario)


def test_a_client_that_leaves_mid_stream_stops_the_provider_and_the_proxy_keeps_serving():
    sent = []

    async def provider(request):
        if request.headers.get("X-Test") != "stream":
            return web.json_response({"ok": True})
        reply = web.StreamResponse()
        await reply.prepare(request)
        for i in range(400):
            await reply.write(b"x" * 100)
            sent.append(i)
            await asyncio.sleep(0.01)
        return reply

    async def scenario():
        async with running(provider) as (client, url):
            async with client.post(url, json=CHAT, headers={"X-Test": "stream"}) as r:
                await r.content.read(100)
            await asyncio.sleep(0.5)
            seen = len(sent)
            await asyncio.sleep(0.5)
            assert len(sent) == seen < 400  # the provider stopped being read
            async with client.post(url, json=CHAT) as r:
                assert r.status == 200

    run(scenario)


def test_a_silent_provider_gives_a_504():
    async def provider(request):
        await asyncio.sleep(5)
        return web.json_response({})

    async def scenario():
        async with running(provider, upstream_timeout=0.3) as (client, url):
            async with client.post(url, json=CHAT) as r:
                assert r.status == 504 and (await r.json())["error"]["type"] == "timeout"

    run(scenario)


def test_a_provider_401_is_the_clients_own_problem_in_open_mode_and_ours_in_tenant_mode():
    async def provider(request):
        return web.json_response({"error": {"message": "bad key"}}, status=401)

    async def scenario():
        async with running(provider) as (client, url):
            async with client.post(url, json=CHAT) as r:
                assert (r.status, (await r.json())["error"]["message"]) == (401, "bad key")
        async with running(provider, keys=tenants(("acme", 1, "k1"))) as (client, url):
            async with client.post(url, json=CHAT, headers={"Authorization": "Bearer k1"}) as r:
                assert r.status == 502 and "credentials" in (await r.json())["error"]["message"]

    run(scenario)


def test_a_provider_that_keeps_saying_429_is_retried_a_few_times_then_the_client_gets_its_429_and_body():
    calls = []

    async def provider(request):
        calls.append(1)
        return web.json_response({"error": {"code": "insufficient_quota"}}, status=429, headers={"Retry-After": "7"})

    async def scenario():
        async with running(provider, limit=6000, max_rate_limit_retries=2) as (client, url):
            async with client.post(url, json=CHAT) as r:
                assert r.status == 429 and r.headers["Retry-After"] == "7" and (await r.json())["error"]["code"] == "insufficient_quota"
        assert len(calls) == 3  # the first try and two retries

    run(scenario)


def test_a_retry_after_date_does_not_break_the_retry():
    calls = []

    async def provider(request):
        calls.append(1)
        if len(calls) == 1:
            return web.Response(status=429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})  # a date, not seconds
        return web.json_response({"ok": True})

    async def scenario():
        async with running(provider, limit=600) as (client, url):
            async with client.post(url, json=CHAT) as r:
                assert r.status == 200
        assert len(calls) == 2

    run(scenario)


OK = {"Authorization": "Bearer k1"}


async def ok_provider(request):
    return web.json_response({})


def test_events_and_balances_survive_a_restart_and_the_balance_keeps_regenerating():
    with temp_schema() as (conn, url):
        keys = tenants(("acme", 1, "k1"))

        async def first_life():
            async with running(ok_provider, keys=keys, pool=10, cap_seconds=60, database=url) as (client, front):
                async with client.post(front, json=CHAT, headers={**OK, "X-Hermes-User-Facing": "true"}) as r:
                    assert r.status == 200

        run(first_life)
        row = conn.execute("SELECT r.finished_at IS NOT NULL, q.tenant_id, q.outcome, q.status FROM experiment_runs r JOIN requests q ON q.run_id = r.id").fetchone()
        assert row == (True, "acme", "result", 200)  # the run was finished and the request stored with its tenant
        saved = conn.execute("SELECT balance FROM credit_balances WHERE tenant_id = 'acme'").fetchone()[0]
        assert saved < 600  # a full balance is 10 credits a second for 60 seconds; the win spent some

        async def second_life():
            with Engine(arena=100) as engine:
                proxy = Proxy("http://127.0.0.1:1/x", engine, 600, keys=keys, pool=10, cap_seconds=60, database=url)
                front, _ = await serve(proxy.app(), **RUNNER_ARGS)
                try:
                    assert saved <= proxy._gateway.balances()["acme"] < 600  # not refilled by the restart
                finally:
                    await front.cleanup()

        run(second_life)


def test_a_crash_leaves_open_requests_that_the_next_start_marks_cancelled():
    with temp_schema() as (conn, url):
        dead = create_run(conn, "proxy", "exchange")
        conn.execute("INSERT INTO requests (run_id, request_id, gateway, t_request) VALUES (%s, 'lost', 'exchange', 1.0)", (dead,))
        conn.commit()

        async def scenario():
            async with running(ok_provider, database=url):
                pass

        run(scenario)
        assert conn.execute("SELECT outcome, error FROM requests WHERE request_id = 'lost'").fetchone() == ("cancelled", "restarted")
        assert conn.execute("SELECT finished_at IS NOT NULL FROM experiment_runs WHERE id = %s", (dead,)).fetchone()[0]


def test_shutting_down_answers_the_calls_still_waiting_with_a_503_instead_of_leaving_them_hanging():
    events = []

    async def scenario():
        upstream, upstream_url = await serve(_app(ok_provider))
        with Engine(arena=100) as engine:
            front, url = await serve(Proxy(upstream_url + CHAT_PATH, engine, 6, on_event=events.append).app(), **RUNNER_ARGS)  # a slice every 10s
            async with aiohttp.ClientSession() as client:
                async with client.post(url + CHAT_PATH, json=CHAT) as r:  # takes the slice resting at start
                    assert r.status == 200
                waiting = asyncio.create_task(client.post(url + CHAT_PATH, json=CHAT))
                await until(lambda: [e["event"] for e in events].count("bid") == 2)
                await front.cleanup()
                async with await waiting as r:
                    assert r.status == 503 and r.headers["Retry-After"] == "1"
        await upstream.cleanup()

    run(scenario)


def test_metrics_and_health_describe_the_proxy_and_the_metrics_token_guards_the_tenants_names():
    async def scenario():
        keys = tenants(("acme", 1, "k1"))
        async with running(ok_provider, limit=6, keys=keys, metrics_token="s3cret") as (client, url):
            base = url.removesuffix(CHAT_PATH)
            async with client.post(url, json=CHAT, headers=OK) as r:  # takes the slice resting at start
                assert r.status == 200
            queued = asyncio.create_task(client.post(url, json=CHAT, headers=OK))  # waits ten seconds for the next
            await asyncio.sleep(0.3)
            async with client.get(base + "/metrics") as r:
                assert r.status == 401
            async with client.get(base + "/metrics", headers={"Authorization": "Bearer s3cret"}) as r:
                lines = (await r.text()).splitlines()
            assert 'hermes_fills_total{tenant="acme"} 1' in lines and 'hermes_queue_depth{tenant="acme"} 1' in lines
            assert any(l.startswith('hermes_credit_balance{tenant="acme"}') for l in lines)
            async with client.get(base + "/health") as r:
                assert (r.status, await r.json()) == (200, {"status": "ok", "problems": []})
            queued.cancel()

    run(scenario)


def test_health_says_degraded_while_balances_cannot_be_saved_and_down_when_the_exchange_has_stopped():
    async def scenario():
        holder = {}
        async with running(ok_provider, keys=tenants(("acme", 1, "k1")), holder=holder) as (client, url):
            base, proxy = url.removesuffix(CHAT_PATH), holder["proxy"]
            proxy._balances_saved = False
            async with client.get(base + "/health") as r:
                body = await r.json()
                assert r.status == 200 and body["status"] == "degraded" and "balances" in body["problems"][0]
            real = proxy._gateway
            proxy._gateway = type("Stopped", (), {"alive": False, "__exit__": real.__exit__})()  # as if the exchange thread had died
            async with client.get(base + "/health") as r:
                assert r.status == 503 and (await r.json())["status"] == "down"
            proxy._gateway = real

    run(scenario)


def test_a_proxy_whose_database_is_unreachable_refuses_to_start_instead_of_serving_without_its_records():
    async def scenario():
        with Engine(arena=100) as engine:
            proxy = Proxy("http://127.0.0.1:1/x", engine, 600, database="postgresql://nobody@127.0.0.1:1/none")
            front, _ = await serve(proxy.app(), **RUNNER_ARGS)

    with pytest.raises(Exception):
        run(scenario)
