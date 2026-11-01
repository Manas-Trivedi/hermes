import type { HermesEvent } from "./events";

// What one tenant is doing right now and has done since the dashboard connected.
export type TenantStats = {
  queued: number; // waiting for a slice
  sending: number; // won a slice, with the provider
  fills: number;
  paid: number; // total price paid over those fills
  rejections: number; // 429s: wasted retries
  cancelled: number;
  ok: number; // finished with a 200
  failed: number; // finished with anything else
};

type State = "queued" | "sending";

export type Tenants = { stats: ReadonlyMap<string, TenantStats>; open: ReadonlyMap<string, { tenant: string; state: State }> };

export const emptyTenants: Tenants = { stats: new Map(), open: new Map() };

// A feed that drops and reconnects can leave requests whose end was never seen. Bound the memory they take.
export const MAX_OPEN = 5000;

const blank = (): TenantStats => ({ queued: 0, sending: 0, fills: 0, paid: 0, rejections: 0, cancelled: 0, ok: 0, failed: 0 });

export const tenantOf = (e: HermesEvent): string => (typeof e.tenant_id === "string" ? e.tenant_id : "default");

export function applyToTenants(t: Tenants, e: HermesEvent): Tenants {
  if (!["request", "fill", "forward", "rejected", "result", "cancelled"].includes(e.event)) return t;
  const tenant = tenantOf(e);
  const stats = new Map(t.stats);
  const open = new Map(t.open);
  const s = { ...(stats.get(tenant) ?? blank()) };
  const was = open.get(e.request_id);
  if (was) s[was.state] -= 1;
  let state: State | null = was?.state ?? null;
  switch (e.event) {
    case "request":
    case "rejected":
      state = "queued";
      if (e.event === "rejected") s.rejections += 1;
      break;
    case "fill":
      state = "sending"; // the call leaves right after the fill; "forward" repeats this
      s.fills += 1;
      s.paid += typeof e.paid === "number" ? e.paid : 0;
      break;
    case "forward":
      state = "sending";
      break;
    case "result":
      state = null;
      if (e.status === 200) s.ok += 1;
      else s.failed += 1;
      break;
    case "cancelled":
      state = null;
      s.cancelled += 1;
      break;
  }
  if (state) {
    s[state] += 1;
    open.delete(e.request_id);
    open.set(e.request_id, { tenant, state });
  } else {
    open.delete(e.request_id);
  }
  while (open.size > MAX_OPEN) open.delete(open.keys().next().value as string);
  stats.set(tenant, s);
  return { stats, open };
}
