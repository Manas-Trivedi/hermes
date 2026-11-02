import { recentLives, type Lives } from "./lives";

const WINDOW = 60; // seconds of history shown
const WIDTH = 600;
const ROW = 12;
const COLORS = { waiting: "var(--wait)", sending: "var(--accent)" };

// One row per request; grey while it waits for a slice, blue while the backend has it.
export function Timelines({ lives }: { lives: Lives }) {
  const from = lives.now - WINDOW;
  const x = (t: number) => Math.max(0, ((t - from) / WINDOW) * WIDTH);
  return (
    <section>
      <h2>Timelines (last {WINDOW}s)</h2>
      <p>
        <span style={{ color: COLORS.waiting }}>■</span> waiting for a slice · <span style={{ color: COLORS.sending }}>■</span> with the backend · ✕ rejected (429)
      </p>
      {[...new Set([...lives.byId.values()].map((l) => l.agent))].sort().map((agent) => {
        const rows = recentLives(lives, agent, WINDOW);
        return (
          <div key={agent}>
            <b>{agent}</b> ({rows.length})
            <svg width={WIDTH} height={Math.max(rows.length, 1) * ROW + 2} className="lane">
              {rows.map((life, row) =>
                life.segments.map((s, i) => {
                  const end = s.end ?? lives.now;
                  return (
                    <g key={`${life.id}-${i}`}>
                      <rect x={x(s.start)} y={row * ROW + 1} width={Math.max(1, x(end) - x(s.start))} height={ROW - 3} fill={COLORS[s.kind]}>
                        <title>{`${life.id}: ${s.kind}`}</title>
                      </rect>
                      {s.kind === "sending" && s.end !== null && life.segments[i + 1]?.kind === "waiting" && (
                        <text x={x(end)} y={row * ROW + ROW - 2} fontSize={ROW} fill="var(--ink)">✕</text>
                      )}
                    </g>
                  );
                }),
              )}
            </svg>
          </div>
        );
      })}
    </section>
  );
}
