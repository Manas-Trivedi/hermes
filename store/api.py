"""Stored experiment results over HTTP, for the dashboard's comparison chart.

    uv run python -m store.api --database postgresql://... --port 8766

GET /runs returns the finished runs with the numbers the chart compares, and
GET /agents the same numbers for each agent within each run. A run that never
finished (it crashed, or is still going) is left out so a half-run can't pass
for a result. Connections are opened per request; this serves a dashboard, not
load.

For each run (and for each agent in it), over its requests:
  completed        results that came back 200
  failures         requests that were cancelled, or ended on anything but a 200
  wasted_retries   calls the backend rejected with a 429
  completion_time  first request to last result or cancel, in seconds
  p95_latency      95th percentile of request to result, over results, in seconds
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from store.db import connect

# The agents' names (agents/), kept here because the results server runs in a
# container that has only this package.
AGENTS = ("pr-review", "support", "research")

_METRICS = """
       count(q.request_id),
       count(*) FILTER (WHERE q.outcome = 'result' AND q.status = 200),
       count(*) FILTER (WHERE q.outcome = 'cancelled' OR (q.outcome = 'result' AND q.status IS DISTINCT FROM 200)),
       coalesce(sum(q.rejections), 0),
       max(q.t_end) - min(q.t_request),
       percentile_cont(0.95) WITHIN GROUP (ORDER BY q.t_end - q.t_request) FILTER (WHERE q.outcome = 'result')
"""

_SUMMARY = f"""
SELECT r.id, r.name, r.condition, r.seed, r.started_at, {_METRICS}
FROM experiment_runs r
LEFT JOIN requests q ON q.run_id = r.id
WHERE r.finished_at IS NOT NULL
GROUP BY r.id
ORDER BY r.id
"""

# Request ids are "<agent>-<key>" (agents/base.py) and agent names contain hyphens
# ("pr-review"), so the agent is the known name the id starts with, not the text
# before the first hyphen. A request no agent claims is reported as "other".
_PER_AGENT = f"""
SELECT r.id, coalesce(a.agent, 'other'), {_METRICS}
FROM experiment_runs r
JOIN requests q ON q.run_id = r.id
LEFT JOIN unnest(%s::text[]) AS a(agent) ON starts_with(q.request_id, a.agent || '-')
WHERE r.finished_at IS NOT NULL
GROUP BY r.id, coalesce(a.agent, 'other')
ORDER BY r.id, 2
"""

_METRIC_FIELDS = ("requests", "completed", "failures", "wasted_retries", "completion_time", "p95_latency")
_FIELDS = ("id", "name", "condition", "seed", "started_at") + _METRIC_FIELDS


def run_summaries(conn) -> list[dict]:
    rows = [dict(zip(_FIELDS, row)) for row in conn.execute(_SUMMARY).fetchall()]
    for row in rows:
        row["started_at"] = row["started_at"].isoformat()
        row["wasted_retries"] = int(row["wasted_retries"])
    return rows


def agent_summaries(conn) -> list[dict]:
    rows = [dict(zip(("run_id", "agent") + _METRIC_FIELDS, row)) for row in conn.execute(_PER_AGENT, (list(AGENTS),)).fetchall()]
    for row in rows:
        row["wasted_retries"] = int(row["wasted_retries"])
    return rows


def make_server(url: str, port: int = 8766, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            summaries = {"/runs": ("runs", run_summaries), "/agents": ("agents", agent_summaries)}.get(self.path)
            if summaries is None:
                self.send_error(404)
                return
            key, summarise = summaries
            with connect(url) as conn:
                body = json.dumps({key: summarise(conn)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")  # the dashboard is served from another port
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    p = argparse.ArgumentParser(description="Serve stored experiment results to the dashboard")
    p.add_argument("--database", required=True)
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside a container")
    a = p.parse_args()
    server = make_server(a.database, a.port, a.host)
    print(f"results on http://{a.host}:{server.server_port}/runs")
    server.serve_forever()


if __name__ == "__main__":
    main()
