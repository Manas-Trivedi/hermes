"""Shared base for the bidder agents: no framework, plain calls through a gateway.

An agent turns a piece of work (a PR, a ticket, a research task) into a pipeline
of stages. The calls inside a stage run at the same time, and a stage starts
only when the one before it succeeded. If a stage fails, the rest is not sent,
because spending capacity on a result that can no longer be used is waste.

Every call declares its urgency as TaskMeta. The deadline is set once for the
whole item, so later stages of a slow item are more urgent than its first.
An agent built with `inflate=True` lies: it declares every call as user facing
and due now, which is the dishonest agent the experiment needs.

A call waits for its result with the agent's own timeout and cancels when it
runs out (the gateways have no timeouts of their own). A cancel that loses the
race to a fill means the call is already going out, so the agent waits for it.
"""

import json
import threading
import time
from dataclasses import dataclass, field, replace

from pricing import TaskMeta


class PromptSender:
    """Wraps an HttpSender so each request carries its prompt as the body.

    The gateways call send(request_id) and know nothing about prompts, so the
    agent registers the prompt under the request id first. A retry after a 429
    sends the same prompt again.
    """

    def __init__(self, sender):
        self._sender = sender
        self._bodies: dict[str, bytes] = {}

    def register(self, request_id: str, prompt: str) -> None:
        self._bodies[request_id] = json.dumps({"prompt": prompt}).encode()

    def forget(self, request_id: str) -> None:
        self._bodies.pop(request_id, None)

    def __call__(self, request_id: str):
        return self._sender(request_id, self._bodies[request_id])


@dataclass(frozen=True)
class Outcome:
    """What happened to one call."""

    agent: str
    request_id: str
    submitted_at: float
    finished_at: float
    status: int | None  # final HTTP status; None if it was never answered
    attempts: int  # calls sent to the backend, so attempts - 1 were rejected with a 429
    gave_up: bool  # the agent's timeout ran out first

    @property
    def ok(self) -> bool:
        return self.status == 200


@dataclass
class ItemResult:
    """What happened to one piece of work."""

    agent: str
    item_id: str
    started_at: float
    finished_at: float
    ok: bool  # every stage ran and succeeded
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def duration(self) -> float:
        return self.finished_at - self.started_at


class Agent:
    name = ""
    user_facing = False
    deadline_in = 60.0  # seconds from the start of an item until its result is needed

    def __init__(self, adapter, sender: PromptSender, tenant_id: str = "default", inflate: bool = False,
                 call_timeout: float = 120.0, clock=time.monotonic):
        self._adapter = adapter
        self._sender = sender
        self._tenant_id = tenant_id
        self._inflate = inflate
        self._call_timeout = call_timeout
        self._clock = clock

    def run(self, item) -> ItemResult:
        """Do one piece of work. Blocks until it is done or has failed."""
        raise NotImplementedError

    def _run_stages(self, item_id: str, stages: list[tuple[list[tuple[str, str]], str | None]]) -> ItemResult:
        """`stages` is a list of (calls, batch_id), each call being (key, prompt)."""
        started = self._clock()
        due = started + self.deadline_in
        outcomes, ok = [], True
        for calls, batch_id in stages:
            results = self._stage(calls, due, batch_id)
            outcomes += results
            if not all(o.ok for o in results):
                ok = False
                break
        return ItemResult(self.name, item_id, started, self._clock(), ok, outcomes)

    def _stage(self, calls: list[tuple[str, str]], due: float, batch_id: str | None) -> list[Outcome]:
        results: list[Outcome | None] = [None] * len(calls)

        def work(i: int) -> None:
            results[i] = self._call(*calls[i], due, batch_id)

        threads = [threading.Thread(target=work, args=(i,)) for i in range(len(calls))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def _call(self, key: str, prompt: str, due: float, batch_id: str | None) -> Outcome:
        request_id = f"{self.name}-{key}"
        now = self._clock()
        meta = TaskMeta(self._tenant_id, now, due, self.user_facing, batch_id, self.name)
        if self._inflate:
            meta = replace(meta, deadline=now, user_facing=True, batch_id=None)
        self._sender.register(request_id, prompt)
        task = self._adapter.submit(request_id, meta)
        gave_up = not task.wait(self._call_timeout)
        if gave_up and not self._adapter.cancel(task):
            gave_up = not task.wait(self._call_timeout)  # the call won a slice first and is going out
        if task.wait(0):
            self._sender.forget(request_id)  # a call still in flight may yet be retried, so keep its prompt
        return Outcome(self.name, request_id, now, self._clock(), task.status, task.attempts, gave_up)
