import type { HermesEvent } from "./events";

// Where a request spends its time: queued for a slice, or out with the backend.
export type Segment = { kind: "waiting" | "sending"; start: number; end: number | null }; // end null: still going

export type Life = {
  id: string;
  agent: string;
  segments: Segment[];
  done: "result" | "cancelled" | null;
  status: number | null; // final HTTP status
  rejections: number; // 429s: wasted retries
};

export type Lives = { byId: ReadonlyMap<string, Life>; origin: number | null; now: number };

export const emptyLives: Lives = { byId: new Map(), origin: null, now: 0 };

export const MAX_LIVES = 300;

const AGENTS = ["pr-review", "support", "research"];

// Request ids are "<agent>-<key>" (agents/base.py).
export function agentOf(requestId: string): string {
  return AGENTS.find((a) => requestId.startsWith(a + "-")) ?? requestId.split("-")[0];
}

export function applyToLives(lives: Lives, e: HermesEvent): Lives {
  if (e.event === "bid" || e.event === "reprice" || e.event === "fill") {
    return { ...lives, origin: lives.origin ?? e.t, now: Math.max(lives.now, e.t) };
  }
  const byId = new Map(lives.byId);
  // A request seen first mid-life (the dashboard joined late) starts waiting from now.
  const old = byId.get(e.request_id);
  const life: Life = old
    ? { ...old, segments: old.segments.map((s) => ({ ...s })) }
    : { id: e.request_id, agent: agentOf(e.request_id), segments: [{ kind: "waiting", start: e.t, end: null }], done: null, status: null, rejections: 0 };
  const open = life.segments[life.segments.length - 1];
  const close = () => {
    if (open && open.end === null) open.end = e.t;
  };
  switch (e.event) {
    case "forward":
      close();
      life.segments.push({ kind: "sending", start: e.t, end: null });
      break;
    case "rejected":
      close();
      life.rejections += 1;
      life.segments.push({ kind: "waiting", start: e.t, end: null });
      break;
    case "result":
      close();
      life.done = "result";
      life.status = typeof e.status === "number" ? e.status : null;
      break;
    case "cancelled":
      close();
      life.done = "cancelled";
      break;
  }
  byId.delete(e.request_id); // re-insert so the map stays in order of latest activity
  byId.set(e.request_id, life);
  while (byId.size > MAX_LIVES) byId.delete(byId.keys().next().value as string);
  return { byId, origin: lives.origin ?? e.t, now: Math.max(lives.now, e.t) };
}

// The lives to draw for one agent: still going, or finished inside the last `window` seconds.
export function recentLives(lives: Lives, agent: string, window: number): Life[] {
  const from = lives.now - window;
  return [...lives.byId.values()].filter((l) => {
    if (l.agent !== agent) return false;
    const last = l.segments[l.segments.length - 1];
    return l.done === null || (last.end ?? lives.now) >= from;
  });
}
