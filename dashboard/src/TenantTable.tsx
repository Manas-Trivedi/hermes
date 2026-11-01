import type { Tenants } from "./tenants";

export function TenantsTable({ tenants }: { tenants: Tenants }) {
  const rows = [...tenants.stats.entries()].sort(([a], [b]) => a.localeCompare(b));
  return (
    <section>
      <h2>Tenants</h2>
      {rows.length === 0 ? (
        <p className="muted">No requests seen yet.</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th align="left">tenant</th>
              <th align="right">waiting</th>
              <th align="right">with provider</th>
              <th align="right">fills</th>
              <th align="right">avg price paid</th>
              <th align="right">429s</th>
              <th align="right">cancelled</th>
              <th align="right">ok</th>
              <th align="right">failed</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([tenant, s]) => (
              <tr key={tenant}>
                <td>{tenant}</td>
                <td align="right">{s.queued}</td>
                <td align="right">{s.sending}</td>
                <td align="right">{s.fills}</td>
                <td align="right">{s.fills ? (s.paid / s.fills).toFixed(1) : "–"}</td>
                <td align="right">{s.rejections}</td>
                <td align="right">{s.cancelled}</td>
                <td align="right">{s.ok}</td>
                <td align="right">{s.failed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
