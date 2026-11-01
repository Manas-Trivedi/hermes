import { describe, expect, it } from "vitest";
import type { HermesEvent } from "./events";
import { agentOf, applyToLives, emptyLives, MAX_LIVES, recentLives } from "./lives";

const ev = (event: string, request_id: string, t: number, fields: object = {}): HermesEvent => ({
  event, gateway: "exchange", request_id, t, attempt: 0, ...fields,
});
const play = (events: HermesEvent[]) => events.reduce(applyToLives, emptyLives);

describe("request lives", () => {
  it("splits a request with a 429 into waiting and sending stretches", () => {
    const life = play([
      ev("request", "support-t0-triage", 0),
      ev("bid", "support-t0-triage", 0.1, { offered: 5 }),
      ev("fill", "support-t0-triage", 2, { paid: 5, offered: 5 }),
      ev("forward", "support-t0-triage", 2),
      ev("rejected", "support-t0-triage", 2.1),
      ev("forward", "support-t0-triage", 5),
      ev("result", "support-t0-triage", 6, { status: 200 }),
    ]).byId.get("support-t0-triage")!;
    expect(life.segments.map((s) => [s.kind, s.start, s.end])).toEqual([
      ["waiting", 0, 2], ["sending", 2, 2.1], ["waiting", 2.1, 5], ["sending", 5, 6],
    ]);
    expect([life.done, life.status, life.rejections, life.agent]).toEqual(["result", 200, 1, "support"]);
  });

  it("ends a cancelled request's wait where it was cancelled", () => {
    const life = play([ev("request", "research-q0-p1", 0), ev("cancelled", "research-q0-p1", 3)]).byId.get("research-q0-p1")!;
    expect([life.done, life.segments[0].end]).toEqual(["cancelled", 3]);
  });

  it("starts a request seen mid-life from the first event it sees, and does not mix up the original", () => {
    const before = play([ev("forward", "pr-review-pr0-f0", 10)]);
    const after = applyToLives(before, ev("result", "pr-review-pr0-f0", 12, { status: 200 }));
    expect(before.byId.get("pr-review-pr0-f0")!.segments.at(-1)!.end).toBeNull();
    expect(after.byId.get("pr-review-pr0-f0")!.segments.map((s) => s.kind)).toEqual(["waiting", "sending"]);
  });

  it("names the agent from the request id, including the hyphenated one", () => {
    expect(["pr-review-pr3-f1", "support-t2-answer", "research-q1-synthesis"].map(agentOf)).toEqual(["pr-review", "support", "research"]);
  });

  it("shows an agent's open requests and recently finished ones, and keeps memory bounded", () => {
    const lives = play([
      ev("request", "support-old", 0), ev("result", "support-old", 1, { status: 200 }),
      ev("request", "support-open", 2),
      ev("request", "research-x", 100),
    ]);
    expect(recentLives(lives, "support", 60).map((l) => l.id)).toEqual(["support-open"]);
    const many = play(Array.from({ length: MAX_LIVES + 5 }, (_, i) => ev("request", `support-${i}`, i)));
    expect(many.byId.size).toBe(MAX_LIVES);
  });
});
