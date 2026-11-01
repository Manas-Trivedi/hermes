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

Giving up: a client that disconnects while its call waits has its bid taken out
of the book; one that disconnects once the call has won stops the upstream read
and frees the connection. The provider may stay silent for `upstream_timeout`
seconds (504 before the reply starts; a cut stream after). A provider 429 is
retried up to `max_rate_limit_retries` times and then handed to the client with
its own body, so a quota that cannot recover does not loop forever. Each 429 also
slows the release rate (`adaptive`, scheduler.capacity). In tenant
mode the credentials upstream are the proxy's own, so a provider 401 or 403 is
our fault, not the client's, and becomes a 502.

Health and metrics: GET /health says ok, degraded (still serving, but events
are not being stored or balances not saved) or, with a 503, down. GET /metrics
is Prometheus text (gateway.metrics); with `metrics_token` set it needs that
token as a bearer token, because it names the tenants and their traffic.

Restarts: with a database, every event is stored (the process's lifetime is
one run called "proxy"), each tenant's credit balance is saved every few seconds
and on shutdown, and the next start picks the balances up and lets them keep
regenerating for the time the proxy was down. The book itself is not saved: it
starts empty. On a clean shutdown the calls still waiting for a slice are
answered 503 at once, and the ones already out are given time to finish. After a
crash, the requests the dead process left open are marked cancelled. This needs a
single proxy process per database, which the in-memory book needs anyway.

Parsing a body runs off the event loop. Nothing in the reply is parsed.
"""

import argparse
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass

import aiohttp
from aiohttp import web

from client import Engine
from gateway.config import Config, ConfigError, hash_key, load
from gateway.exchange import ExchangeGateway
from gateway.metrics import Metrics
from gateway.sender import Reply
from gateway.tokens import estimate_tokens
from pricing import AgentConfig, Budgets, Scorer, TaskMeta
from store import EventWriter, apply_schema, close_unfinished_runs, connect, create_run, finish_run, load_balances, save_balances

log = logging.getLogger("hermes.proxy")
RUN_NAME = "proxy"

CHAT_PATH = "/v1/chat/completions"
MAX_BODY = 64 * 1024 * 1024
RUNNER_ARGS = {"handler_cancellation": True}  # without it a client that hangs up leaves its bid in the book
_HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade"}
_NOT_FORWARDED = _HOP_BY_HOP | {"host", "content-length"}


def retry_after(headers) -> float:
    """Seconds from a Retry-After header. A date, or anything unreadable, counts as none."""
    try:
        return max(0.0, float(headers.get("Retry-After") or 0))
    except ValueError:
        return 0.0


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
    task: object = None  # the exchange's Task for the call
    rejections: int = 0  # provider 429s so far


class Proxy:
    def __init__(self, upstream: str, engine: Engine, limit_per_minute: float, tokens_per_minute: float | None = None,
                 default_max_tokens: int = 1024, scorer: Scorer | None = None, on_event=None, clock=time.monotonic,
                 keys: dict | None = None, upstream_key: str | None = None, pool: float | None = None, cap_seconds: float = 60.0,
                 upstream_timeout: float = 120.0, max_rate_limit_retries: int = 3,
                 adaptive: bool = True, database: str | None = None, balance_save_seconds: float = 5.0,
                 metrics_token: str | None = None):
        """`keys` maps the sha256 of an API key to its Tenant (gateway.config); without it the proxy is open."""
        self._upstream = upstream
        self._engine = engine
        self._limit = limit_per_minute
        self._tokens_per_minute = tokens_per_minute
        self._default_max_tokens = default_max_tokens
        self._scorer = scorer or Scorer()
        self._on_event = on_event
        self._clock = clock
        self._upstream_timeout = upstream_timeout
        self._max_retries = max_rate_limit_retries
        self._adaptive = adaptive
        self._metrics = Metrics()
        self._metrics_token = metrics_token
        self._balances_saved = True  # whether the latest save worked
        self._database = database
        self._balance_save_seconds = balance_save_seconds
        self._writer: EventWriter | None = None
        self._run_id: int | None = None
        self._saver: asyncio.Task | None = None
        self.balance_save_failures = 0
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
                   keys=config.keys, upstream_key=config.upstream_key, pool=config.pool, cap_seconds=config.cap_seconds,
                   upstream_timeout=config.timeout_seconds, max_rate_limit_retries=config.max_rate_limit_retries, adaptive=config.adaptive,
                   database=config.database_url, balance_save_seconds=config.balance_save_seconds,
                   metrics_token=config.metrics_token, **kw)

    def app(self) -> web.Application:
        app = web.Application(client_max_size=MAX_BODY)
        app.router.add_post(CHAT_PATH, self._chat)
        app.router.add_get("/health", self._health)
        app.router.add_get("/metrics", self._metrics_page)
        app.on_startup.append(self._start)
        app.on_shutdown.append(self._drain)
        app.on_cleanup.append(self._stop)
        return app

    async def _start(self, app) -> None:
        self._loop = asyncio.get_running_loop()
        if self._database:
            await self._loop.run_in_executor(None, self._open_database)
        # Bytes go through untouched, so the client sees the provider's own encoding; the pool is unbounded
        # because the exchange, not the pool, decides how many calls are out.
        self._session = aiohttp.ClientSession(auto_decompress=False, connector=aiohttp.TCPConnector(limit=0),
                                              timeout=aiohttp.ClientTimeout(total=None, sock_connect=10, sock_read=self._upstream_timeout))
        self._gateway = ExchangeGateway(
            self._send, self._engine, self._limit, clock=self._clock, on_event=self._events(),
            rescore=lambda task, now: self._scorer.score(task.meta, now).price, tokens_per_minute=self._tokens_per_minute,
            budgets=self._budgets, adaptive=self._adaptive,
        )
        self._gateway.__enter__()
        if self._database and self._budgets:
            self._saver = asyncio.create_task(self._save_balances_forever())

    def _open_database(self) -> None:
        """Close what a crash left open, restore the saved balances, and start this process's run."""
        with connect(self._database) as conn:
            apply_schema(conn)  # safe to repeat, and a fresh database needs it
            if closed := close_unfinished_runs(conn, RUN_NAME):
                log.warning("closed %d run(s) left open by a crash; their in-flight requests are marked cancelled", closed)
            if self._budgets:
                saved, away = load_balances(conn)
                self._budgets.restore(saved, away, self._clock())
            self._run_id = create_run(conn, RUN_NAME, "exchange", params={"requests_per_minute": self._limit, "tokens_per_minute": self._tokens_per_minute})
        self._writer = EventWriter(self._database, self._run_id)

    def _events(self):
        sinks = [s for s in (self._on_event, self._writer, self._metrics) if s is not None]
        return lambda event: [sink(event) for sink in sinks]

    async def _save_balances_forever(self) -> None:
        while True:
            await asyncio.sleep(self._balance_save_seconds)
            await self._save_balances()

    async def _save_balances(self) -> None:
        try:
            balances = await self._loop.run_in_executor(None, self._gateway.balances)
            await self._loop.run_in_executor(None, self._write_balances, balances)
            self._balances_saved = True
        except Exception:
            self._balances_saved = False
            self.balance_save_failures += 1
            log.exception("could not save credit balances (%d failures so far)", self.balance_save_failures)

    def _write_balances(self, balances: dict[str, float]) -> None:
        with connect(self._database) as conn:
            save_balances(conn, balances)

    async def _health(self, request: web.Request) -> web.Response:
        if not self._gateway.alive:
            return web.json_response({"status": "down", "reason": "the exchange stopped"}, status=503)
        problems = []
        if self._writer is not None and self._writer.error is not None:
            problems.append("events are not being stored")
        if not self._balances_saved:
            problems.append("credit balances are not being saved")
        return web.json_response({"status": "degraded" if problems else "ok", "problems": problems})

    async def _metrics_page(self, request: web.Request) -> web.Response:
        if self._metrics_token and request.headers.get("Authorization") != f"Bearer {self._metrics_token}":
            return error_response(401, "missing or wrong metrics token", "invalid_request_error")
        depths, balances = await self._loop.run_in_executor(None, lambda: (self._gateway.queue_depth(), self._gateway.balances()))
        text = self._metrics.render(depths, balances, self._gateway.rate_scale, self.balance_save_failures,
                                    self._writer is not None and self._writer.error is not None)
        return web.Response(text=text, content_type="text/plain", charset="utf-8", headers={"X-Content-Type-Options": "nosniff"})

    async def _drain(self, app) -> None:
        """Shutting down: answer the calls still waiting for a slice with a 503 instead of making them wait."""
        for call in list(self._calls.values()):
            if call.task is not None and self._gateway.cancel(call.task) and not call.done.done():
                call.done.set_result(web.json_response(
                    {"error": {"message": "the proxy is restarting; try again", "type": "server_error", "code": None}},
                    status=503, headers={"Retry-After": "1"}))

    async def _stop(self, app) -> None:
        if self._saver:
            self._saver.cancel()
        await self._loop.run_in_executor(None, self._gateway.__exit__, None, None, None)
        if self._database:
            if self._budgets:
                await self._save_balances()
            await self._loop.run_in_executor(None, self._close_database)
        await self._session.close()

    def _close_database(self) -> None:
        try:
            self._writer.close()
        except RuntimeError:
            log.exception("events were lost: the event writer failed")
        with connect(self._database) as conn:
            finish_run(conn, self._run_id)

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
        call.task = task = self._gateway.submit(request_id, self._scorer.score(meta, now).price, meta, tokens)
        try:
            return await call.done
        finally:
            del self._calls[request_id]
            if not call.done.done() or call.done.cancelled():  # the client hung up (cancelling the handler cancels the future): withdraw the bid
                self._gateway.cancel(task)  # a no-op if it already won; _forward then finds no call

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
                    call.rejections += 1
                    if call.rejections <= self._max_retries:
                        return Reply(429, retry_after(upstream.headers))
                elif upstream.status in (401, 403) and self._keys:
                    return self._answer(call, error_response(502, "the provider rejected the proxy's credentials", "api_connection_error"), 502)
                reply = web.StreamResponse(status=upstream.status, reason=upstream.reason,
                                           headers={k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP})
                await reply.prepare(call.request)
                try:
                    async for chunk in upstream.content.iter_any():
                        await reply.write(chunk)
                    await reply.write_eof()
                except ConnectionResetError:
                    pass  # the client left mid-reply; leaving the block closes the upstream connection
                except (aiohttp.ClientError, asyncio.TimeoutError):
                    call.request.transport.close()  # the headers are out, so the only honest signal is a cut stream
                return self._answer(call, reply, upstream.status, final=True, retry_after=retry_after(upstream.headers))
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            timed_out = isinstance(e, (asyncio.TimeoutError, aiohttp.ServerTimeoutError))
            status, kind = (504, "timeout") if timed_out else (502, "api_connection_error")
            return self._answer(call, error_response(status, f"upstream {'timed out' if timed_out else 'failed'}: {type(e).__name__}", kind), status)
        except BaseException:
            self._answer(call, error_response(500, "proxy error", "server_error"), 500)
            raise

    @staticmethod
    def _answer(call: _Call, response: web.StreamResponse, status: int, final: bool = False, retry_after: float = 0.0) -> Reply:
        if not call.done.done():  # a cancelled future is done: the client hung up and the handler is gone
            call.done.set_result(response)
        return Reply(status, retry_after, retry=not final)


def main() -> None:
    p = argparse.ArgumentParser(description="OpenAI-compatible proxy that schedules calls through the exchange")
    p.add_argument("--config", required=True, help="the TOML config file (gateway/config.py)")
    p.add_argument("--arena", type=int, default=10000, help="most bids the book can hold at once")
    a = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        config = load(a.config)
    except (OSError, ConfigError) as e:
        raise SystemExit(f"config error: {e}")
    with Engine(arena=a.arena) as engine:
        web.run_app(Proxy.from_config(config, engine).app(), host=config.host, port=config.port, print=lambda *_: None, **RUNNER_ARGS)


if __name__ == "__main__":
    main()
