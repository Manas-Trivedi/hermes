import { useEffect, useState } from "react";
import { CONDITIONS, METRICS, experimentNames, latestPerCondition, type RunSummary } from "./compare";

const API_URL = new URLSearchParams(window.location.search).get("api") ?? "http://127.0.0.1:8766/runs";

// Categorical slots 1-3 of the reference palette, one per condition and fixed
// (color follows the condition, not its rank). The aqua is under 3:1 on white,
// so every bar also carries its value and the table below has the same numbers.
const COLORS = { fifo: "#2a78d6", priority: "#eb6834", exchange: "#1baf7a" };
const INK = "#0b0b0b";
const MUTED = "#52514e";

const PANEL = { w: 200, h: 140, top: 18, bottom: 6 };

const fmt = (v: number | null | undefined, unit: string) => (v == null ? "–" : `${Number.isInteger(v) ? v : v.toFixed(1)}${unit}`);

export function Comparison() {
  const [runs, setRuns] = useState<RunSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState<string | null>(null);

  const load = () =>
    fetch(API_URL)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((body) => {
        setRuns(body.runs);
        setError(null);
      })
      .catch((e) => setError(String(e.message ?? e)));

  useEffect(() => {
    load();
  }, []);

  const names = experimentNames(runs ?? []);
  const chosen = name && names.includes(name) ? name : names[0];
  const byCondition = chosen ? latestPerCondition(runs ?? [], chosen) : {};

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
      {error && <p>Results unavailable: {error}</p>}
      {runs && names.length === 0 && <p>No finished runs stored yet.</p>}
      {chosen && (
        <>
          <p style={{ color: MUTED }}>
            {CONDITIONS.map((c) => (
              <span key={c} style={{ marginRight: 16 }}>
                <span style={{ color: COLORS[c] }}>■</span> {c}
              </span>
            ))}
            · lower is better in every panel
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 16 }}>
            {METRICS.map((m) => {
              const values = CONDITIONS.map((c) => byCondition[c]?.[m.key] ?? null);
              const max = Math.max(...values.map((v) => v ?? 0), 1e-9);
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
                      const barH = v == null ? 0 : (v / max) * (PANEL.h - PANEL.top - PANEL.bottom);
                      const x = i * slot + slot * 0.2;
                      const y = PANEL.h - PANEL.bottom - barH;
                      return (
                        <g key={c}>
                          <rect x={x} y={y} width={slot * 0.6} height={barH} fill={COLORS[c]} rx={3}>
                            <title>{`${c}: ${fmt(v, m.unit)}`}</title>
                          </rect>
                          <text x={x + slot * 0.3} y={y - 4} textAnchor="middle" fontSize={12} fill={INK}>
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
            <table>
              <thead>
                <tr>
                  <th align="left">condition</th>
                  <th align="left">run</th>
                  <th align="left">requests</th>
                  <th align="left">completed</th>
                  {METRICS.map((m) => (
                    <th key={m.key} align="left">
                      {m.title}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {CONDITIONS.map((c) => {
                  const r = byCondition[c];
                  return (
                    <tr key={c}>
                      <td>{c}</td>
                      <td>{r?.id ?? "–"}</td>
                      <td>{r?.requests ?? "–"}</td>
                      <td>{r?.completed ?? "–"}</td>
                      {METRICS.map((m) => (
                        <td key={m.key}>{fmt(r?.[m.key], m.unit)}</td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </details>
        </>
      )}
    </section>
  );
}
