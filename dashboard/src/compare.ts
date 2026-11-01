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

export type MetricKey = "completion_time" | "p95_latency" | "failures" | "wasted_retries";

// One agent's numbers within one run (the same metrics as RunSummary).
export type AgentSummary = Pick<RunSummary, MetricKey | "requests" | "completed"> & { run_id: number; agent: string };

export const METRICS: { key: MetricKey; title: string; unit: string }[] = [
  { key: "completion_time", title: "Completion time", unit: "s" },
  { key: "p95_latency", title: "P95 latency", unit: "s" },
  { key: "failures", title: "Failures", unit: "" },
  { key: "wasted_retries", title: "Wasted retries", unit: "" },
];

// An experiment is the runner's "<name>/<variant>" without the seed: its runs are the repeats.
export const experimentOf = (runName: string) => runName.replace(/\/seed\d+$/, "");

// Experiments, the one with the most recently stored run first.
export function experimentNames(runs: RunSummary[]): string[] {
  const newest = new Map<string, number>();
  for (const r of runs) newest.set(experimentOf(r.name), Math.max(newest.get(experimentOf(r.name)) ?? 0, r.id));
  return [...newest.entries()].sort((a, b) => b[1] - a[1]).map(([name]) => name);
}

// A metric over the repeats of one condition. Runs with no value (a run where nothing finished) are left out of the
// mean and range; n counts the runs.
export type Stat = { n: number; mean: number | null; min: number | null; max: number | null };
export type Stats = Record<MetricKey, Stat>;

function stat(values: (number | null)[]): Stat {
  const v = values.filter((x): x is number => x != null);
  return { n: values.length, mean: v.length ? v.reduce((a, b) => a + b, 0) / v.length : null, min: v.length ? Math.min(...v) : null, max: v.length ? Math.max(...v) : null };
}

export function statsOf(rows: Pick<RunSummary, MetricKey>[]): Stats {
  return Object.fromEntries(METRICS.map((m) => [m.key, stat(rows.map((r) => r[m.key]))])) as Stats;
}

// For one experiment, the numbers under each condition over all its runs (one per seed).
export function perCondition(runs: RunSummary[], experiment: string): Partial<Record<Condition, Stats>> {
  const out: Partial<Record<Condition, Stats>> = {};
  for (const c of CONDITIONS) {
    const rows = runs.filter((r) => r.condition === c && experimentOf(r.name) === experiment);
    if (rows.length) out[c] = statsOf(rows);
  }
  return out;
}

// The same, for each agent: agent -> condition -> stats.
export function perAgent(runs: RunSummary[], agents: AgentSummary[], experiment: string): Record<string, Partial<Record<Condition, Stats>>> {
  const condition = new Map(runs.filter((r) => experimentOf(r.name) === experiment).map((r) => [r.id, r.condition as Condition]));
  const out: Record<string, Partial<Record<Condition, Stats>>> = {};
  for (const agent of new Set(agents.filter((a) => condition.has(a.run_id)).map((a) => a.agent))) {
    out[agent] = {};
    for (const c of CONDITIONS) {
      const rows = agents.filter((a) => a.agent === agent && condition.get(a.run_id) === c);
      if (rows.length) out[agent][c] = statsOf(rows);
    }
  }
  return out;
}
