import { useEffect, useState } from "react";
import { Comparison } from "./Comparison";
import { Fills } from "./Fills";
import { OrderBook } from "./OrderBook";
import { TenantsTable } from "./TenantTable";
import { Timelines } from "./Timelines";
import { loadConfig, type DashboardConfig } from "./config";
import { useFeed } from "./useFeed";

export function App() {
  const [config, setConfig] = useState<DashboardConfig | null>(null);
  useEffect(() => {
    loadConfig(window.location.search).then(setConfig);
  }, []);
  return config ? <Dashboard config={config} /> : <main />;
}

function Dashboard({ config }: { config: DashboardConfig }) {
  const { status, events, book, fills, lives, tenants } = useFeed(config.feed);
  return (
    <main>
      <h1>Hermes</h1>
      <p className="muted">
        <span className={`dot ${status}`} /> feed {status} · {events.length} recent events
      </p>
      <TenantsTable tenants={tenants} />
      <OrderBook book={book} />
      <Fills fills={fills} />
      <Timelines lives={lives} />
      {config.results && <Comparison apiUrl={config.results} />}
      <section>
        <h2>Recent events</h2>
        <table>
          <thead>
            <tr>
              <th align="left">t</th>
              <th align="left">tenant</th>
              <th align="left">gateway</th>
              <th align="left">event</th>
              <th align="left">request</th>
              <th align="left">attempt</th>
              <th align="left">details</th>
            </tr>
          </thead>
          <tbody>
            {events.map((e, i) => {
              const { event, gateway, request_id, t, attempt, tenant_id, ...details } = e;
              return (
                <tr key={i}>
                  <td>{t.toFixed(3)}</td>
                  <td>{typeof tenant_id === "string" ? tenant_id : ""}</td>
                  <td>{gateway}</td>
                  <td>{event}</td>
                  <td>{request_id}</td>
                  <td>{attempt}</td>
                  <td>{JSON.stringify(details)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </section>
    </main>
  );
}
