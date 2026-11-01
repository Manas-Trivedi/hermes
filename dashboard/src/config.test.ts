import { describe, expect, it } from "vitest";
import { DEFAULTS, loadConfig } from "./config";

describe("dashboard config", () => {
  it("uses the defaults when there is no config file", async () => {
    expect(await loadConfig("", () => Promise.reject(new Error("404")))).toEqual(DEFAULTS);
  });

  it("takes the file over the defaults, lets null hide the comparison, and lets the address win over both", async () => {
    const file = () => Promise.resolve({ feed: "wss://hermes.example/feed?token=t", results: null });
    expect(await loadConfig("", file)).toEqual({ feed: "wss://hermes.example/feed?token=t", results: null });
    expect(await loadConfig("?feed=ws://x:1&api=http://y/runs", file)).toEqual({ feed: "ws://x:1", results: "http://y/runs" });
  });

  it("ignores a config file of the wrong shape instead of breaking the page", async () => {
    expect(await loadConfig("", () => Promise.resolve({ feed: 5, results: 7 }))).toEqual(DEFAULTS);
    expect(await loadConfig("", () => Promise.resolve("not an object"))).toEqual(DEFAULTS);
  });
});
