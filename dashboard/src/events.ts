// One event from a gateway, as the feed sends it (see the event log format in gateway/events.py).
export type HermesEvent = {
  event: string;
  gateway: string;
  request_id: string;
  t: number;
  attempt: number;
  [field: string]: unknown;
};

export const MAX_EVENTS = 200;

// Parse one feed message; null if it is not an event.
export function parseEvent(message: string): HermesEvent | null {
  try {
    const e = JSON.parse(message);
    return e && typeof e.event === "string" && typeof e.request_id === "string" ? e : null;
  } catch {
    return null;
  }
}

// Newest first, keeping only the latest `max`.
export function addEvent(events: HermesEvent[], e: HermesEvent, max = MAX_EVENTS): HermesEvent[] {
  return [e, ...events].slice(0, max);
}
