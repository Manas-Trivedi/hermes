// Where the dashboard finds the feed and the stored results. Looked up when the page loads, so one built
// page can be pointed at any deployment: a ?feed= or ?api= in the address wins, then /config.json next to the
// page, then the defaults for a local run.
export type DashboardConfig = {
  feed: string;
  results: string | null; // the results server's /runs URL; null hides the comparison
};

export const DEFAULTS: DashboardConfig = { feed: "ws://127.0.0.1:8765", results: "http://127.0.0.1:8766/runs" };

export async function loadConfig(search: string, fetchJson: (url: string) => Promise<unknown> = defaultFetch): Promise<DashboardConfig> {
  let file: Partial<DashboardConfig> = {};
  try {
    const body = await fetchJson("/config.json");
    if (body && typeof body === "object") file = body as Partial<DashboardConfig>;
  } catch {
    // no config file: a local run
  }
  const params = new URLSearchParams(search);
  return {
    feed: params.get("feed") ?? (typeof file.feed === "string" ? file.feed : DEFAULTS.feed),
    results: params.get("api") ?? (file.results === null || typeof file.results === "string" ? file.results : DEFAULTS.results),
  };
}

const defaultFetch = async (url: string) => {
  const r = await fetch(url);
  if (!r.ok || !(r.headers.get("content-type") ?? "").includes("json")) throw new Error(`HTTP ${r.status}`); // the dev server answers unknown paths with the page
  return r.json();
};
