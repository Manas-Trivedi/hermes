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
from gateway.proxy import CHAT_PATH, Proxy

BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
pytestmark = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")

CHAT = {"model": "m", "messages": [{"role": "user", "content": "hi"}], "max_tokens": 4}


async def serve(app: web.Application) -> tuple[web.AppRunner, str]:
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"


@asynccontextmanager
async def running(handler, limit=600, **proxy_args):
    """A fake provider running `handler`, a proxy in front of it, and a client session."""
    upstream, upstream_url = await serve(_app(handler))
    with Engine(arena=1000) as engine:
        front, front_url = await serve(Proxy(upstream_url + CHAT_PATH, engine, limit, **proxy_args).app())
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
            front, url = await serve(Proxy("http://127.0.0.1:1/v1/chat/completions", engine, 600).app())
            try:
                async with aiohttp.ClientSession() as client:
                    async with client.post(url + CHAT_PATH, json=CHAT) as r:
                        assert r.status == 502 and (await r.json())["error"]["type"] == "api_connection_error"
            finally:
                await front.cleanup()

    run(scenario)
