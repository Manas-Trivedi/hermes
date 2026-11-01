import { useEffect, useState } from "react";
import { addEvent, parseEvent, type HermesEvent } from "./events";

export type Status = "connecting" | "open" | "closed";

const RETRY_MS = 1000;

// Follows the feed, reconnecting when it drops. Events from before the
// connection are not replayed by the feed, so a reconnect leaves a gap.
export function useFeed(url: string): { status: Status; events: HermesEvent[] } {
  const [status, setStatus] = useState<Status>("connecting");
  const [events, setEvents] = useState<HermesEvent[]>([]);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry: number | undefined;
    let stopped = false;

    const connect = () => {
      setStatus("connecting");
      ws = new WebSocket(url);
      ws.onopen = () => setStatus("open");
      ws.onmessage = (m) => {
        const e = parseEvent(String(m.data));
        if (e) setEvents((prev) => addEvent(prev, e));
      };
      ws.onclose = () => {
        if (stopped) return;
        setStatus("closed");
        retry = window.setTimeout(connect, RETRY_MS);
      };
    };

    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retry);
      ws?.close();
    };
  }, [url]);

  return { status, events };
}
