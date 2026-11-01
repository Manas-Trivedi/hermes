import { describe, expect, it } from "vitest";
import { experimentNames, latestPerCondition, type RunSummary } from "./compare";

const run = (id: number, name: string, condition: string): RunSummary => ({
  id, name, condition, requests: 1, completed: 1, failures: 0, wasted_retries: 0, completion_time: 1, p95_latency: 1,
});

describe("comparison data", () => {
  const runs = [run(1, "a", "fifo"), run(2, "a", "exchange"), run(3, "b", "fifo"), run(4, "a", "fifo"), run(5, "a", "mystery")];

  it("takes the latest run per condition inside one experiment and ignores other experiments and unknown conditions", () => {
    const got = latestPerCondition(runs, "a");
    expect(got.fifo?.id).toBe(4);
    expect(got.exchange?.id).toBe(2);
    expect(got.priority).toBeUndefined();
    expect(Object.keys(got).sort()).toEqual(["exchange", "fifo"]);
  });

  it("lists experiments newest first", () => {
    expect(experimentNames(runs)).toEqual(["a", "b"]);
  });
});
