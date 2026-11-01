"""Counters and gauges for the proxy, in Prometheus text format (GET /metrics).

Counters are built from the shared event log (gateway.events), so every number
here agrees with what is stored. Gauges (queue depth, credit balances, the rate
scale) are read from the gateway when the page is asked for. Labels are the
tenant (a handful, fixed by the config) and the HTTP status of a result.
"""

import threading
from collections import Counter

_HELP = {
    "hermes_requests_total": ("counter", "Requests accepted into the exchange."),
    "hermes_fills_total": ("counter", "Slices won."),
    "hermes_rejections_total": ("counter", "Calls the provider rejected with a 429 (wasted retries)."),
    "hermes_cancelled_total": ("counter", "Requests withdrawn before they were sent."),
    "hermes_results_total": ("counter", "Finished requests by final HTTP status (0: sending failed)."),
    "hermes_last_clearing_price": ("gauge", "Price the latest fill paid, in ticks."),
    "hermes_queue_depth": ("gauge", "Requests waiting for a slice."),
    "hermes_credit_balance": ("gauge", "Credits a tenant can spend now."),
    "hermes_rate_scale": ("gauge", "Share of the configured release rate in use (adaptive capacity)."),
    "hermes_balance_save_failures_total": ("counter", "Failed saves of credit balances."),
    "hermes_event_writer_failed": ("gauge", "1 if storing events has stopped."),
}


class Metrics:
    """Pass an instance as a gateway's on_event; gateways call it from several threads."""

    def __init__(self):
        self._lock = threading.Lock()
        self._counts: Counter = Counter()
        self._last_price: int | None = None

    def __call__(self, event: dict) -> None:
        tenant = event.get("tenant_id", "default")
        kind = event["event"]
        with self._lock:
            if kind == "request":
                self._counts["hermes_requests_total", (("tenant", tenant),)] += 1
            elif kind == "fill":
                self._counts["hermes_fills_total", (("tenant", tenant),)] += 1
                self._last_price = event["paid"]
            elif kind == "rejected":
                self._counts["hermes_rejections_total", (("tenant", tenant),)] += 1
            elif kind == "cancelled":
                self._counts["hermes_cancelled_total", (("tenant", tenant),)] += 1
            elif kind == "result":
                self._counts["hermes_results_total", (("status", str(event["status"] or 0)), ("tenant", tenant))] += 1

    def render(self, depths: dict[str, int], balances: dict[str, float], rate_scale: float, save_failures: int, writer_failed: bool) -> str:
        with self._lock:
            samples = dict(self._counts)
            last_price = self._last_price
        for tenant, depth in depths.items():
            samples["hermes_queue_depth", (("tenant", tenant),)] = depth
        for tenant, balance in balances.items():
            samples["hermes_credit_balance", (("tenant", tenant),)] = balance
        samples["hermes_rate_scale", ()] = rate_scale
        samples["hermes_balance_save_failures_total", ()] = save_failures
        samples["hermes_event_writer_failed", ()] = int(writer_failed)
        if last_price is not None:
            samples["hermes_last_clearing_price", ()] = last_price
        lines = []
        for name, (kind, help_text) in _HELP.items():
            rows = sorted((labels, value) for (n, labels), value in samples.items() if n == name)
            if rows:
                lines += [f"# HELP {name} {help_text}", f"# TYPE {name} {kind}"]
                lines += [f"{name}{_labels(labels)} {_number(value)}" for labels, value in rows]
        return "\n".join(lines) + "\n"


def _number(value) -> str:
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def _labels(labels: tuple) -> str:
    escape = lambda v: v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return "{" + ",".join(f'{k}="{escape(v)}"' for k, v in labels) + "}" if labels else ""
