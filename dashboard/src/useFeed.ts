import { useEffect, useState } from "react";
import { applyToBook, emptyBook, type Book } from "./book";
import { addEvent, parseEvent, type HermesEvent } from "./events";
import { agentOf, applyToLives, emptyLives, type Lives } from "./lives";

export type Fill = { t: number; id: string; agent: string; paid: number; offered: number };

const MAX_FILLS = 100;

export type Status = "connecting" | "open" | "closed";

const RETRY_MS = 1000;

// Follows the feed, reconnecting when it drops. Events from before the
// connection are not replayed by the feed, so a reconnect leaves a gap.
export function useFeed(url: string): { status: Status; events: HermesEvent[]; book: Book; fills: Fill[]; lives: Lives } {
  const [status, setStatus] = useState<Status>("connecting");
  const [events, setEvents] = useState<HermesEvent[]>([]);
  const [book, setBook] = useState<Book>(emptyBook);
  const [fills, setFills] = useState<Fill[]>([]);
  const [lives, setLives] = useState<Lives>(emptyLives);

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
        if (!e) return;
        setEvents((prev) => addEvent(prev, e));
        setBook((prev) => applyToBook(prev, e));
        setLives((prev) => applyToLives(prev, e));
        if (e.event === "fill") {
          const fill = { t: e.t, id: e.request_id, agent: agentOf(e.request_id), paid: e.paid as number, offered: e.offered as number };
          setFills((prev) => [fill, ...prev].slice(0, MAX_FILLS));
        }
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

  return { status, events, book, fills, lives };
}
