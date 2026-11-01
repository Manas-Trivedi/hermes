"""The drop-in proxy: an OpenAI-compatible endpoint that schedules calls through the exchange.

    uv run python -m gateway.proxy --config hermes.toml

Agents point their base URL here. POST /v1/chat/completions is read just far
enough to price it (prompt size, max_tokens, optional urgency headers), then
the call waits in the exchange until it wins a slice, and only then is it sent
upstream. The reply, streamed or not, goes back to the client byte for byte.

How it fits the thread-based ExchangeGateway: the gateway already sends each
winning call on a thread of its own and wants a status back, so `send` hands the
call to this event loop and waits. The loop opens the upstream request, and only
once it has a status other than 429 starts answering the client. A 429 is
reported to the gateway, which bids again, and the client never sees it.

Tenants: with `[[tenants]]` in the config, every request must carry
`Authorization: Bearer <api key>` of one of them (else 401). The key picks the
tenant, which is on every event of the request and pays from its own credit
budget (pricing.Budgets, one balance per tenant, the pool split by `share`).
The client's key is never sent upstream: the provider's own key from the config
replaces it. With no tenants the proxy is open, has no budgets, and passes the
client's Authorization through, which is for local use.

Urgency headers (all optional, removed before the call goes upstream):
    X-Hermes-User-Facing: true|false    a person is waiting
    X-Hermes-Deadline-Seconds: 30       when the answer is needed, from now
    X-Hermes-Batch: <id>                one call of a bulk job

Parsing a body runs off the event loop. Nothing in the reply is parsed.
"""

import argparse
import asyncio
import json
import time
import uuid
from dataclasses import dataclass

import aiohttp
from aiohttp import web

from client import Engine
from gateway.config import Config, ConfigError, hash_key, load
from gateway.exchange import ExchangeGateway
from gateway.sender import Reply
from gateway.tokens import estimate_tokens
from pricing import AgentConfig, Budgets, Scorer, TaskMeta

CHAT_PATH = "/v1/chat/completions"
MAX_BODY = 64 * 1024 * 1024
_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}
_NOT_FORWARDED = _HOP_BY_HOP | {"host", "content-length"}


class BadRequest(ValueError):
    pass


def error_response(status: int, message: str, kind: str) -> web.Response:
    """An error in the shape OpenAI clients expect."""
    return web.json_response({"error": {"message": message, "type": kind, "code": None}}, status=status)


def inspect_body(body: bytes, default_max_tokens: int) -> int:
    """The estimated tokens of a chat completion body. Raises BadRequest if it is not one."""
    try:
        data = json.loads(body)
    except ValueError:
        raise BadRequest("the body is not valid JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("messages"), list):
        raise BadRequest("the body needs a 'messages' list")
    texts = []
    for message in data["messages"]:
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, str):
            texts.append(content)
        elif isinstance(content, list):  # content parts: text, images, ...
            texts += [p["text"] for p in content if isinstance(p, dict) and isinstance(p.get("text"), str)]
    max_tokens = data.get("max_completion_tokens", data.get("max_tokens"))
    if max_tokens is None:
        max_tokens = default_max_tokens
    if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens < 0:
        raise BadRequest("max_tokens must be a non-negative integer")
    return estimate_tokens("".join(texts), max_tokens)


def urgency(headers, now: float, tenant_id: str = "default") -> TaskMeta:  # agent_id is set by the caller
    """Task metadata from the X-Hermes-* headers. Raises BadRequest on a value it cannot read."""
    flag = headers.get("X-Hermes-User-Facing", "false").strip().lower()
    if flag not in ("true", "false"):
        raise BadRequest("X-Hermes-User-Facing must be true or false")
    deadline = None
    if (seconds := headers.get("X-Hermes-Deadline-Seconds")) is not None:
        try:
            deadline = now + float(seconds)
        except ValueError:
            raise BadRequest("X-Hermes-Deadline-Seconds must be a number") from None
    return TaskMeta(tenant_id=tenant_id, enqueued_at=now, deadline=deadline, user_facing=flag == "true",
                    batch_id=headers.get("X-Hermes-Batch"), agent_id=tenant_id)  # a tenant's budget pays for its calls


@dataclass
class _Call:
    request: web.Request
    body: bytes
    done: asyncio.Future  # resolved with the response to return, once the call has been answered


class Proxy:
    def __init__(self, upstream: str, engine: Engine, limit_per_minute: float, tokens_per_minute: float | None = None,
                 default_max_tokens: int = 1024, scorer: Scorer | None = None, on_event=None, clock=time.monotonic,
                 keys: dict | None = None, upstream_key: str | None = None, pool: float | None = None, cap_seconds: float = 60.0):
        """`keys` maps the sha256 of an API key to its Tenant (gateway.config); without it the proxy is open."""
        self._upstream = upstream
        self._engine = engine
        self._limit = limit_per_minute
        self._tokens_per_minute = tokens_per_minute
        self._default_max_tokens = default_max_tokens
        self._scorer = scorer or Scorer()
        self._on_event = on_event
        self._clock = clock
        self._keys = keys or {}
        self._upstream_key = upstream_key
        self._budgets = None
        if self._keys:
            tenants = {t.id: AgentConfig(1.0, t.share) for t in self._keys.values()}
            self._budgets = Budgets(tenants, clock(), pool if pool is not None else limit_per_minute, cap_seconds)
        self._calls: dict[str, _Call] = {}
        self._loop: asyncio.AbstractEventLoop
        self._session: aiohttp.ClientSession
        self._gateway: ExchangeGateway

    @classmethod
    def from_config(cls, config: Config, engine: Engine, **kw) -> "Proxy":
        return cls(config.upstream_url, engine, config.requests_per_minute, config.tokens_per_minute, config.default_max_tokens,
                   keys=config.keys, upstream_key=config.upstream_key, pool=config.pool, cap_seconds=config.cap_seconds, **kw)

    def app(self) -> web.Application:
        app = web.Application(client_max_size=MAX_BODY)
        app.router.add_post(CHAT_PATH, self._chat)
        app.on_startup.append(self._start)
        app.on_cleanup.append(self._stop)
        return app

    async def _start(self, app) -> None:
        self._loop = asyncio.get_running_loop()
        # Bytes go through untouched, so the client sees the provider's own encoding; the pool is unbounded
        # because the exchange, not the pool, decides how many calls are out.
        self._session = aiohttp.ClientSession(auto_decompress=False, connector=aiohttp.TCPConnector(limit=0),
                                              timeout=aiohttp.ClientTimeout(total=None, sock_connect=10))
        self._gateway = ExchangeGateway(
            self._send, self._engine, self._limit, clock=self._clock, on_event=self._on_event,
            rescore=lambda task, now: self._scorer.score(task.meta, now).price, tokens_per_minute=self._tokens_per_minute,
            budgets=self._budgets,
        )
        self._gateway.__enter__()

    async def _stop(self, app) -> None:
        await self._loop.run_in_executor(None, self._gateway.__exit__, None, None, None)
        await self._session.close()

    def _tenant(self, request: web.Request) -> str | None:
        """The id of the tenant whose API key the request carries, or None."""
        scheme, _, key = request.headers.get("Authorization", "").partition(" ")
        tenant = self._keys.get(hash_key(key.strip())) if scheme.lower() == "bearer" else None
        return tenant.id if tenant else None

    async def _chat(self, request: web.Request) -> web.StreamResponse:
        tenant_id = "default"
        if self._keys:
            tenant_id = self._tenant(request)
            if tenant_id is None:
                return error_response(401, "missing or unknown API key", "invalid_request_error")
        body = await request.read()
        now = self._clock()
        try:
            tokens = await self._loop.run_in_executor(None, inspect_body, body, self._default_max_tokens)
            meta = urgency(request.headers, now, tenant_id)
        except BadRequest as e:
            return error_response(400, str(e), "invalid_request_error")
        request_id = f"proxy-{uuid.uuid4().hex}"
        call = _Call(request, body, self._loop.create_future())
        self._calls[request_id] = call
        try:
            self._gateway.submit(request_id, self._scorer.score(meta, now).price, meta, tokens)
            return await call.done
        finally:
            del self._calls[request_id]

    def _send(self, request_id: str) -> Reply:
        """Runs on the gateway's thread for a call that won a slice; waits for the loop to answer the client."""
        return asyncio.run_coroutine_threadsafe(self._forward(request_id), self._loop).result()

    async def _forward(self, request_id: str) -> Reply:
        call = self._calls.get(request_id)
        if call is None:  # the client went away while the call was winning
            return Reply(499)
        try:
            headers = {k: v for k, v in call.request.headers.items() if k.lower() not in _NOT_FORWARDED and not k.lower().startswith("x-hermes-")}
            if self._keys:  # the client's key is ours, not the provider's
                headers = {k: v for k, v in headers.items() if k.lower() != "authorization"}
                if self._upstream_key:
                    headers["Authorization"] = f"Bearer {self._upstream_key}"
            async with self._session.post(self._upstream, data=call.body, headers=headers) as upstream:
                if upstream.status == 429:
                    return Reply(429, float(upstream.headers.get("Retry-After") or 0))
                reply = web.StreamResponse(status=upstream.status, reason=upstream.reason,
                                           headers={k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP})
                await reply.prepare(call.request)
                try:
                    async for chunk in upstream.content.iter_any():
                        await reply.write(chunk)
                    await reply.write_eof()
                except aiohttp.ClientError:
                    call.request.transport.close()  # the headers are out, so the only honest signal is a cut stream
                call.done.set_result(reply)
                return Reply(upstream.status)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if not call.done.done():
                call.done.set_result(error_response(502, f"upstream failed: {type(e).__name__}", "api_connection_error"))
            return Reply(502)
        except BaseException:
            if not call.done.done():
                call.done.set_result(error_response(500, "proxy error", "server_error"))
            raise


def main() -> None:
    p = argparse.ArgumentParser(description="OpenAI-compatible proxy that schedules calls through the exchange")
    p.add_argument("--config", required=True, help="the TOML config file (gateway/config.py)")
    p.add_argument("--arena", type=int, default=10000, help="most bids the book can hold at once")
    a = p.parse_args()
    try:
        config = load(a.config)
    except (OSError, ConfigError) as e:
        raise SystemExit(f"config error: {e}")
    with Engine(arena=a.arena) as engine:
        web.run_app(Proxy.from_config(config, engine).app(), host=config.host, port=config.port, print=lambda *_: None)


if __name__ == "__main__":
    main()
