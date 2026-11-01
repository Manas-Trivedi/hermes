import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agents import Agent, PromptSender
from agents.tests.helpers import FakeAdapter
from gateway import HttpSender


class Probe(Agent):
    """Runs the stages it is given, so the base can be tested on its own."""

    name = "probe"
    deadline_in = 30.0

    def __init__(self, stages, *args, **kw):
        super().__init__(*args, **kw)
        self._stages = stages

    def run(self, item):
        return self._run_stages(item, self._stages)


def make(stages, adapter, **kw):
    return Probe(stages, adapter, PromptSender(None), tenant_id="acme", clock=lambda: 100.0, **kw)


def test_each_call_declares_its_urgency_and_an_inflating_agent_declares_the_maximum_instead():
    stages = [([("a", "p")], "batch-1")]
    honest = FakeAdapter()
    make(stages, honest).run("item")
    [(rid, meta)] = honest.submitted
    assert rid == "probe-a"
    assert (meta.tenant_id, meta.agent_id, meta.enqueued_at) == ("acme", "probe", 100.0)
    assert (meta.deadline, meta.user_facing, meta.batch_id) == (130.0, False, "batch-1")

    liar = FakeAdapter()
    make(stages, liar, inflate=True).run("item")
    [(_, meta)] = liar.submitted
    assert (meta.deadline, meta.user_facing, meta.batch_id) == (100.0, True, None)
    assert meta.agent_id == "probe"  # it still pays from its own budget


def test_a_call_that_times_out_is_cancelled_and_recorded_as_given_up():
    adapter = FakeAdapter(hold=True)
    result = make([([("a", "p")], None)], adapter, call_timeout=0.05).run("item")
    assert adapter.cancelled == adapter.tasks and not result.ok
    [outcome] = result.outcomes
    assert outcome.gave_up and outcome.status is None


def test_a_call_that_wins_a_slice_as_the_agent_gives_up_is_waited_for_not_abandoned():
    adapter = FakeAdapter(hold=True, can_cancel=False)  # the cancel always loses the race
    threading.Timer(0.08, lambda: adapter.tasks[0].finish(200)).start()
    result = make([([("a", "p")], None)], adapter, call_timeout=0.05).run("item")
    assert result.ok and not result.outcomes[0].gave_up


def test_calls_in_a_stage_go_out_together_and_a_failed_stage_stops_the_item():
    adapter = FakeAdapter(hold=True)
    stages = [([("a", "p"), ("b", "p"), ("c", "p")], None), ([("last", "p")], None)]
    box = []
    t = threading.Thread(target=lambda: box.append(make(stages, adapter).run("item")))
    t.start()
    deadline = time.monotonic() + 5
    while len(adapter.tasks) < 3 and time.monotonic() < deadline:
        time.sleep(0.001)
    assert len(adapter.tasks) == 3  # all three submitted while none has finished
    adapter.tasks[0].finish(200)
    adapter.tasks[1].finish(500)
    adapter.tasks[2].finish(200)
    t.join(5)
    [result] = box
    assert not result.ok and len(adapter.submitted) == 3  # the second stage was never sent


def test_the_prompt_travels_as_the_request_body_and_a_retry_resends_it():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            seen.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        sender = PromptSender(HttpSender(f"http://127.0.0.1:{server.server_port}/v1/complete"))
        sender.register("r1", "review this")
        assert sender("r1").status == 200 and sender("r1").status == 200
    finally:
        server.shutdown()
        server.server_close()
    assert seen == [{"prompt": "review this"}] * 2
