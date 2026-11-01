import type { HermesEvent } from "./events";

// A bid resting in the exchange's book, rebuilt from the feed's events.
export type Resting = { id: string; price: number; seq: number; since: number };

export type Book = {
  resting: ReadonlyMap<string, Resting>;
  seq: number; // arrival counter: a raised bid goes to the back of the queue at its new price
  lastPrice: number | null; // what the latest fill paid
  now: number; // t of the latest event, for how long a bid has waited
};

export const emptyBook: Book = { resting: new Map(), seq: 0, lastPrice: null, now: 0 };

export function applyToBook(book: Book, e: HermesEvent): Book {
  const now = Math.max(book.now, e.t);
  switch (e.event) {
    case "bid":
    case "reprice": {
      const resting = new Map(book.resting);
      const since = resting.get(e.request_id)?.since ?? e.t;
      resting.set(e.request_id, { id: e.request_id, price: e.offered as number, seq: book.seq, since });
      return { ...book, resting, seq: book.seq + 1, now };
    }
    case "fill": {
      const resting = new Map(book.resting);
      resting.delete(e.request_id);
      return { ...book, resting, lastPrice: e.paid as number, now };
    }
    case "cancelled": {
      const resting = new Map(book.resting);
      resting.delete(e.request_id);
      return { ...book, resting, now };
    }
    default:
      return { ...book, now };
  }
}

// Best bid first; equal prices in arrival order, as the engine matches them.
export function bidsInOrder(book: Book): Resting[] {
  return [...book.resting.values()].sort((a, b) => b.price - a.price || a.seq - b.seq);
}
