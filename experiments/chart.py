"""Draw the result as one SVG: P95 latency per agent under each condition, honest and inflating.

    uv run python -m experiments.chart --database postgresql://... --name main --out docs/p95-by-agent.svg

Each panel is one agent in one variant. A bar is the mean over seeds of that agent's P95 (seconds,
lower is better) and the line through it runs from the lowest seed to the highest. Every bar carries
its value, since the green is under 3:1 against the page. Colors follow the condition, as on the
dashboard. The chart is drawn on its own light surface so it reads the same wherever it is embedded.
"""

import argparse
import re
from statistics import mean
from xml.sax.saxutils import escape

from store.api import agent_summaries, run_summaries
from store.db import connect

CONDITIONS = ("fifo", "priority", "exchange")
AGENTS = ("support", "research", "pr-review")
COLORS = {"fifo": "#2a78d6", "priority": "#eb6834", "exchange": "#1baf7a"}
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e3e2de"


def collect(conn, name: str) -> dict[str, dict[str, dict[str, list[float]]]]:
    """variant -> agent -> condition -> the agent's P95 in each seed's run."""
    runs = {r["id"]: r for r in run_summaries(conn)}
    out: dict = {}
    for a in agent_summaries(conn):
        run = runs.get(a["run_id"])
        match = run and re.fullmatch(re.escape(name) + r"/([^/]+)/seed\d+", run["name"])
        if match and a["p95_latency"] is not None:
            out.setdefault(match[1], {}).setdefault(a["agent"], {}).setdefault(run["condition"], []).append(a["p95_latency"])
    return out


def render(data: dict, title: str = "P95 latency per agent (seconds, lower is better)") -> str:
    variants = [v for v in ("honest", *sorted(data)) if v in data]
    variants = list(dict.fromkeys(variants))
    pw, ph, left, top, gap = 230, 150, 20, 70, 36
    width = left + 3 * (pw + gap)
    height = top + len(variants) * (ph + 60) + 10
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}" role="img" aria-label="{escape(title)}" font-family="system-ui, sans-serif">',
             f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>',
             f'<text x="{left}" y="26" font-size="16" font-weight="600" fill="{INK}">{escape(title)}</text>']
    for i, c in enumerate(CONDITIONS):
        x = left + i * 110
        parts.append(f'<rect x="{x}" y="40" width="12" height="12" rx="2" fill="{COLORS[c]}"/><text x="{x + 18}" y="51" font-size="12" fill="{MUTED}">{c}</text>')
    for row, variant in enumerate(variants):
        y0 = top + row * (ph + 60)
        label = "all agents honest" if variant == "honest" else f"{variant.removeprefix('inflate-')} declares every call urgent"
        parts.append(f'<text x="{left}" y="{y0 + 4}" font-size="13" font-weight="600" fill="{INK}">{escape(label)}</text>')
        for col, agent in enumerate(AGENTS):
            series = {c: data[variant].get(agent, {}).get(c, []) for c in CONDITIONS}
            top_value = max((max(v) for v in series.values() if v), default=1.0) * 1.15
            x0, base = left + col * (pw + gap), y0 + 24 + ph
            scale = lambda v: base - v / top_value * ph
            parts.append(f'<text x="{x0}" y="{y0 + 22}" font-size="12" fill="{MUTED}">{escape(agent)}</text>'
                         f'<line x1="{x0}" x2="{x0 + pw}" y1="{base}" y2="{base}" stroke="{GRID}"/>')
            for i, c in enumerate(CONDITIONS):
                values = series[c]
                if not values:
                    continue
                bx, bw = x0 + i * pw / 3 + 14, pw / 3 - 28
                m = mean(values)
                parts.append(f'<rect x="{bx:.1f}" y="{scale(m):.1f}" width="{bw:.1f}" height="{base - scale(m):.1f}" fill="{COLORS[c]}" rx="3"><title>{escape(agent)} {c}: {m:.1f}s (lowest {min(values):.1f}, highest {max(values):.1f}, {len(values)} runs)</title></rect>')
                if len(values) > 1:
                    cx = bx + bw / 2
                    parts.append(f'<line x1="{cx:.1f}" x2="{cx:.1f}" y1="{scale(min(values)):.1f}" y2="{scale(max(values)):.1f}" stroke="{INK}" stroke-width="1.5"/>')
                parts.append(f'<text x="{bx + bw / 2:.1f}" y="{scale(max(values)) - 5:.1f}" font-size="12" text-anchor="middle" fill="{INK}">{m:.1f}</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    p = argparse.ArgumentParser(description="Draw per-agent P95 latency from stored runs as an SVG")
    p.add_argument("--database", required=True)
    p.add_argument("--name", default="main")
    p.add_argument("--out", required=True)
    a = p.parse_args()
    with connect(a.database) as conn:
        data = collect(conn, a.name)
    if not data:
        raise SystemExit(f"no finished runs named {a.name}/<variant>/seed<N>")
    with open(a.out, "w") as f:
        f.write(render(data))


if __name__ == "__main__":
    main()
