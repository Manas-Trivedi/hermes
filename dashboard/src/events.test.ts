import { describe, expect, it } from "vitest";
import { addEvent, parseEvent, type HermesEvent } from "./events";

const ev = (id: string): HermesEvent => ({ event: "bid", gateway: "exchange", request_id: id, t: 0, attempt: 0 });

describe("parseEvent", () => {
  it("reads an event and drops anything that is not one", () => {
    expect(parseEvent(JSON.stringify(ev("a")))?.request_id).toBe("a");
    expect(parseEvent("not json")).toBeNull();
    expect(parseEvent("null")).toBeNull();
    expect(parseEvent('{"event": 3}')).toBeNull();
  });
});

describe("addEvent", () => {
  it("puts the newest first and forgets the oldest past the limit", () => {
    const events = addEvent(addEvent(addEvent([], ev("a"), 2), ev("b"), 2), ev("c"), 2);
    expect(events.map((e) => e.request_id)).toEqual(["c", "b"]);
  });
});
