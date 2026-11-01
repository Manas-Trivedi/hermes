import { useEffect, useState } from "react";
import { CONDITIONS, METRICS, experimentNames, perAgent, perCondition, type AgentSummary, type RunSummary, type Stat } from "./compare";


// Categorical slots 1-3 of the reference palette, one per condition and fixed
// (color follows the condition, not its rank). The aqua is under 3:1 on white,
// so every bar also carries its value and the table below has the same numbers.
const COLORS = { fifo: "#2a78d6", priority: "#eb6834", exchange: "#1baf7a" };
const INK = "#0b0b0b";
const MUTED = "#52514e";

const PANEL = { w: 200, h: 140, top: 18, bottom: 6 };

const fmt = (v: number | null | undefined, unit: string) => (v == null ? "–" : `${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`);
const fmtStat = (s: Stat | undefined, unit: string) =>
  !s ? "–" : s.n > 1 && s.mean != null ? `${fmt(s.mean, unit)} (${fmt(s.min, unit)}–${fmt(s.max, unit)})` : fmt(s.mean, unit);

export function Comparison({ apiUrl }: { apiUrl: string }) {
  const API_URL = apiUrl;
  const AGENTS_URL = API_URL.replace(/\/runs$/, "/agents");
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);

  const get = (url: string) => fetch(url).then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))));
  const load = () =>
    Promise.all([get(API_URL), get(AGENTS_URL)])
      .then(([r, a]) => {
        setRuns(r.runs);
        setAgents(a.agents);
        setError(null);
      })
      .catch((e) => setError(String(e.message ?? e)));

  useEffect(() => {
    load();
  }, []);

  const names = experimentNames(runs ?? []);
  const chosen = name && names.includes(name) ? name : names[0];
  const byCondition = chosen ? perCondition(runs ?? [], chosen) : {};
  const byAgent = chosen ? perAgent(runs ?? [], agents, chosen) : {};
  const repeats = Math.max(0, ...CONDITIONS.map((c) => byCondition[c]?.failures.n ?? 0));

  return (
    <section>
      <h2>Comparison</h2>
      <p>
        stored results from {API_URL} <button onClick={load}>reload</button>
        {names.length > 0 && (
          <>
            {" "}
            experiment{" "}
            <select value={chosen} onChange={(e) => setName(e.target.value)}>
              {names.map((n) => (
                <option key={n}>{n}</option>
              ))}
            </select>
          </>
        )}
      </p>
      {error && (
        <p>
          Results unavailable ({error}). Is the results server running? Start it with{" "}
          <code>uv run python -m store.api --database &lt;url&gt;</code>, then reload.
        </p>
      )}
      {runs && names.length === 0 && <p>No finished runs stored yet.</p>}
      {chosen && (
        <>
          <p style={{ color: MUTED }}>
            {CONDITIONS.map((c) => (
              <span key={c} style={{ marginRight: 16 }}>
                <span style={{ color: COLORS[c] }}>■</span> {c}
              </span>
            ))}
            · lower is better in every panel · bar = mean over {repeats} run{repeats === 1 ? "" : "s"} per condition, line = lowest to highest
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
            {METRICS.map((m) => {
              const stats = CONDITIONS.map((c) => byCondition[c]?.[m.key]);
              const values = stats.map((s) => s?.mean ?? null);
              const max = Math.max(...stats.map((s) => s?.max ?? 0), 1e-9);
              const scale = (v: number) => PANEL.h - PANEL.bottom - (v / max) * (PANEL.h - PANEL.top - PANEL.bottom);
              const slot = PANEL.w / CONDITIONS.length;
              return (
                <figure key={m.key} style={{ margin: 0 }}>
                  <figcaption>
                    <b>{m.title}</b>
                  </figcaption>
                  <svg width={PANEL.w} height={PANEL.h} role="img" aria-label={m.title}>
                    <line x1={0} x2={PANEL.w} y1={PANEL.h - PANEL.bottom} y2={PANEL.h - PANEL.bottom} stroke={MUTED} />
                    {CONDITIONS.map((c, i) => {
                      const v = values[i];
                      const y = v == null ? PANEL.h - PANEL.bottom : scale(v);
                      const barH = PANEL.h - PANEL.bottom - y;
                      const x = i * slot + slot * 0.2;
                      const s = stats[i];
                      const spread = s && s.n > 1 && s.min != null && s.max != null;
                      return (
                        <g key={c}>
                          <rect x={x} y={y} width={slot * 0.6} height={barH} fill={COLORS[c]} rx={3}>
                            <title>{`${c}: ${fmtStat(s, m.unit)}`}</title>
                          </rect>
                          {spread && <line x1={x + slot * 0.3} x2={x + slot * 0.3} y1={scale(s.min!)} y2={scale(s.max!)} stroke={INK} strokeWidth={1.5} />}
                          <text x={x + slot * 0.3} y={(spread ? scale(s.max!) : y) - 4} textAnchor="middle" fontSize={12} fill={INK}>
                            {fmt(v, m.unit)}
                          </text>
                        </g>
                      );
                    })}
                  </svg>
                </figure>
              );
            })}
          </div>
          <details>
            <summary>Table</summary>
            <p style={{ color: MUTED }}>mean (lowest–highest) over the runs of each condition</p>
            <table>
              <thead>
                <tr>
                  <th align="left">condition</th>
                  <th align="left">runs</th>
                  {METRICS.map((m) => (
                    <th key={m.key} align="left">
                      {m.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {CONDITIONS.map((c) => (
                  <tr key={c}>
                    <td>{c}</td>
                    <td>{byCondition[c]?.failures.n ?? "–"}</td>
                    {METRICS.map((m) => (
                      <td key={m.key}>{fmtStat(byCondition[c]?.[m.key], m.unit)}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
          <details>
            <summary>Per agent</summary>
            <table>
              <thead>
                <tr>
                  <th align="left">agent</th>
                  <th align="left">condition</th>
                  {METRICS.map((m) => (
                    <th key={m.key} align="left">
                      {m.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(byAgent).flatMap(([agent, conditions]) =>
                  CONDITIONS.map((c) => (
                    <tr key={agent + c}>
                      <td>{agent}</td>
                      <td>{c}</td>
                      {METRICS.map((m) => (
                        <td key={m.key}>{fmtStat(conditions[c]?.[m.key], m.unit)}</td>
                      ))}
                    </tr>
                  )),
                )}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  );
}
