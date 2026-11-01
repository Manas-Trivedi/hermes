import type { Fill } from "./useFeed";

export function Fills({ fills }: { fills: Fill[] }) {
  return (
    <section>
      <h2>Fills</h2>
      <table>
        <thead>
          <tr>
            <th align="left">t</th>
            <th align="left">agent</th>
            <th align="left">request</th>
            <th align="left">paid</th>
            <th align="left">offered</th>
          </tr>
        </thead>
        <tbody>
          {fills.slice(0, 20).map((f, i) => (
            <tr key={i}>
              <td>{f.t.toFixed(3)}</td>
              <td>{f.agent}</td>
              <td>{f.id}</td>
              <td>{f.paid}</td>
              <td>{f.offered}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
