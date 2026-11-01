"""Stored experiment results over HTTP, for the dashboard's comparison chart.

    uv run python -m store.api --database postgresql://... --port 8766

GET /runs returns the finished runs with the numbers the chart compares. A run
that never finished (it crashed, or is still going) is left out so a half-run
can't pass for a result. Connections are opened per request; this serves a
dashboard, not load.

For each run, over its requests:
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

_SUMMARY = """
SELECT r.id, r.name, r.condition, r.seed, r.started_at,
       count(q.request_id),
       count(*) FILTER (WHERE q.outcome = 'result' AND q.status = 200),
       count(*) FILTER (WHERE q.outcome = 'cancelled' OR (q.outcome = 'result' AND q.status IS DISTINCT FROM 200)),
       coalesce(sum(q.rejections), 0),
       max(q.t_end) - min(q.t_request),
       percentile_cont(0.95) WITHIN GROUP (ORDER BY q.t_end - q.t_request) FILTER (WHERE q.outcome = 'result')
FROM experiment_runs r
LEFT JOIN requests q ON q.run_id = r.id
WHERE r.finished_at IS NOT NULL
GROUP BY r.id
ORDER BY r.id
"""

_FIELDS = ("id", "name", "condition", "seed", "started_at", "requests", "completed", "failures",
           "wasted_retries", "completion_time", "p95_latency")


def run_summaries(conn) -> list[dict]:
    rows = [dict(zip(_FIELDS, row)) for row in conn.execute(_SUMMARY).fetchall()]
    for row in rows:
        row["started_at"] = row["started_at"].isoformat()
        row["wasted_retries"] = int(row["wasted_retries"])
    return rows


def make_server(url: str, port: int = 8766) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/runs":
                self.send_error(404)
                return
            with connect(url) as conn:
                body = json.dumps({"runs": run_summaries(conn)}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")  # the dashboard is served from another port
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    p = argparse.ArgumentParser(description="Serve stored experiment results to the dashboard")
    p.add_argument("--database", required=True)
    p.add_argument("--port", type=int, default=8766)
    a = p.parse_args()
    server = make_server(a.database, a.port)
    print(f"results on http://127.0.0.1:{server.server_port}/runs")
    server.serve_forever()


if __name__ == "__main__":
    main()
