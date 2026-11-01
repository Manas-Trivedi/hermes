// Stored results of one run, as the results API sends them (store/api.py).
export type RunSummary = {
  id: number;
  name: string;
  condition: string;
  requests: number;
  completed: number;
  failures: number;
  wasted_retries: number;
  completion_time: number | null;
  p95_latency: number | null;
};

export const CONDITIONS = ["fifo", "priority", "exchange"] as const;
export type Condition = (typeof CONDITIONS)[number];

export const METRICS: { key: "completion_time" | "p95_latency" | "failures" | "wasted_retries"; title: string; unit: string }[] = [
  { key: "completion_time", title: "Completion time", unit: "s" },
  { key: "p95_latency", title: "P95 latency", unit: "s" },
  { key: "failures", title: "Failures", unit: "" },
  { key: "wasted_retries", title: "Wasted retries", unit: "" },
];

// Experiment names, the one run most recently stored first.
export function experimentNames(runs: RunSummary[]): string[] {
  const newest = new Map<string, number>();
  for (const r of runs) newest.set(r.name, Math.max(newest.get(r.name) ?? 0, r.id));
  return [...newest.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name);
}

// For one experiment, the latest run under each condition.
export function latestPerCondition(runs: RunSummary[], name: string): Partial<Record<Condition, RunSummary>> {
  const out: Partial<Record<Condition, RunSummary>> = {};
  for (const r of runs) {
    const c = r.condition as Condition;
    if (r.name === name && CONDITIONS.includes(c) && (out[c]?.id ?? 0) < r.id) out[c] = r;
  }
  return out;
}
