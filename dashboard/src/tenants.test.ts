import { describe, expect, it } from "vitest";
import type { HermesEvent } from "./events";
import { applyToTenants, emptyTenants, MAX_OPEN } from "./tenants";

const ev = (event: string, request_id: string, fields: object = {}): HermesEvent => ({ event, gateway: "exchange", request_id, t: 0, attempt: 0, ...fields });
const play = (events: HermesEvent[]) => events.reduce(applyToTenants, emptyTenants);

describe("tenant view", () => {
  it("follows each request from waiting, to the provider, back to waiting after a 429, to done, per tenant", () => {
    const acme = { tenant_id: "acme" };
    let t = play([ev("request", "a", acme), ev("request", "b", acme), ev("request", "c", { tenant_id: "beta" })]);
    expect([t.stats.get("acme")?.queued, t.stats.get("beta")?.queued]).toEqual([2, 1]);

    t = [ev("fill", "a", { ...acme, paid: 40 }), ev("forward", "a", acme)].reduce(applyToTenants, t);
    expect(t.stats.get("acme")).toMatchObject({ queued: 1, sending: 1, fills: 1, paid: 40 }); // "forward" after "fill" is not a second send

    t = [ev("rejected", "a", acme), ev("fill", "a", { ...acme, paid: 60 }), ev("result", "a", { ...acme, status: 200 })].reduce(applyToTenants, t);
    expect(t.stats.get("acme")).toMatchObject({ queued: 1, sending: 0, fills: 2, paid: 100, rejections: 1, ok: 1 });

    t = [ev("cancelled", "b", acme), ev("result", "c", { tenant_id: "beta", status: 500 })].reduce(applyToTenants, t);
    expect(t.stats.get("acme")).toMatchObject({ queued: 0, cancelled: 1 });
    expect(t.stats.get("beta")).toMatchObject({ queued: 0, failed: 1 });
    expect(t.open.size).toBe(0);
  });

  it("counts events with no tenant (the experiment's) as one tenant and ignores book events", () => {
    const t = play([ev("request", "a"), ev("bid", "a", { offered: 5 }), ev("reprice", "a", { offered: 6 })]);
    expect(t.stats.get("default")?.queued).toBe(1);
  });

  it("does not grow without bound when requests end without the dashboard seeing it", () => {
    const t = play(Array.from({ length: MAX_OPEN + 50 }, (_, i) => ev("request", `r${i}`)));
    expect(t.open.size).toBe(MAX_OPEN);
  });
});
