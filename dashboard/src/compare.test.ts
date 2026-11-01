import { describe, expect, it } from "vitest";
import { experimentNames, experimentOf, perAgent, perCondition, type AgentSummary, type RunSummary } from "./compare";

const run = (id: number, name: string, condition: string, completion_time: number | null = 1, failures = 0): RunSummary => ({
  id, name, condition, requests: 1, completed: 1, failures, wasted_retries: 0, completion_time, p95_latency: 1,
});

describe("comparison data", () => {
  const runs = [run(1, "x/honest/seed1", "fifo", 10), run(2, "x/honest/seed1", "exchange"), run(3, "y/honest/seed1", "fifo"),
    run(4, "x/honest/seed2", "fifo", 20, 2), run(5, "x/honest/seed2", "mystery"), run(6, "x/honest/seed3", "fifo", null)];

  it("treats the seeds of one name and variant as repeats of one experiment, newest first", () => {
    expect(experimentOf("x/inflate-support/seed12")).toBe("x/inflate-support");
    expect(experimentOf("demo")).toBe("demo");
    expect(experimentNames(runs)).toEqual(["x/honest", "y/honest"]);
  });

  it("averages the repeats of a condition, keeps their range, ignores runs with no value, and skips other experiments and unknown conditions", () => {
    const got = perCondition(runs, "x/honest");
    expect(Object.keys(got).sort()).toEqual(["exchange", "fifo"]);
    expect(got.fifo?.completion_time).toEqual({ n: 3, mean: 15, min: 10, max: 20 });
    expect(got.fifo?.failures.mean).toBeCloseTo(2 / 3);
    expect(got.exchange?.completion_time.n).toBe(1);
  });

  it("splits the same numbers by agent", () => {
    const agent = (run_id: number, agent: string, completion_time: number): AgentSummary => ({ ...run(0, "", ""), run_id, agent, completion_time });
    const got = perAgent(runs, [agent(1, "support", 4), agent(4, "support", 8), agent(1, "research", 9), agent(3, "support", 99)], "x/honest");
    expect(Object.keys(got).sort()).toEqual(["research", "support"]); // run 3 belongs to another experiment
    expect(got.support.fifo?.completion_time.mean).toBe(6);
    expect(got.research.exchange).toBeUndefined();
  });
});
