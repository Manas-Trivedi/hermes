import { describe, expect, it } from "vitest";
import { applyToBook, bidsInOrder, emptyBook } from "./book";
import type { HermesEvent } from "./events";

const ev = (event: string, request_id: string, t: number, fields: object = {}): HermesEvent => ({
  event, gateway: "exchange", request_id, t, attempt: 0, ...fields,
});
const play = (events: HermesEvent[]) => events.reduce(applyToBook, emptyBook);
const ids = (events: HermesEvent[]) => bidsInOrder(play(events)).map((b) => b.id);

describe("order book from events", () => {
  it("lists the highest bid first and equal prices in arrival order", () => {
    expect(ids([ev("bid", "a", 0, { offered: 5 }), ev("bid", "b", 1, { offered: 9 }), ev("bid", "c", 2, { offered: 5 })])).toEqual(["b", "a", "c"]);
  });

  it("replaces a raised bid and sends it to the back of its new price, keeping its wait", () => {
    const book = play([
      ev("bid", "a", 0, { offered: 5 }),
      ev("bid", "b", 1, { offered: 7 }),
      ev("reprice", "a", 4, { offered: 7, previous: 5 }),
    ]);
    expect(bidsInOrder(book).map((b) => [b.id, b.price])).toEqual([["b", 7], ["a", 7]]);
    expect(book.now - book.resting.get("a")!.since).toBe(4);
  });

  it("takes a bid out on a fill and remembers what it paid, and on a cancel without touching the price", () => {
    const book = play([
      ev("bid", "a", 0, { offered: 5 }),
      ev("bid", "b", 1, { offered: 7 }),
      ev("bid", "c", 2, { offered: 6 }),
      ev("fill", "b", 3, { paid: 7, offered: 7 }),
      ev("cancelled", "c", 4),
    ]);
    expect(bidsInOrder(book).map((b) => b.id)).toEqual(["a"]);
    expect(book.lastPrice).toBe(7);
  });
});
