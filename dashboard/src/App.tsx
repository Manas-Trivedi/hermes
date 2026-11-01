import { Fills } from "./Fills";
import { OrderBook } from "./OrderBook";
import { Timelines } from "./Timelines";
import { useFeed } from "./useFeed";

const FEED_URL = new URLSearchParams(window.location.search).get("feed") ?? "ws://127.0.0.1:8765";

export function App() {
  const { status, events, book, fills, lives } = useFeed(FEED_URL);
  return (
    <main style={{ fontFamily: "monospace", padding: 16 }}>
      <h1>Hermes</h1>
      <p>
        feed {FEED_URL}: <b>{status}</b> · {events.length} recent events
      </p>
      <OrderBook book={book} />
      <Fills fills={fills} />
      <Timelines lives={lives} />
      <h2>Recent events</h2>
      <table>
        <thead>
          <tr>
            <th align="left">t</th>
            <th align="left">gateway</th>
            <th align="left">event</th>
            <th align="left">request</th>
            <th align="left">attempt</th>
            <th align="left">details</th>
          </tr>
        </thead>
        <tbody>
          {events.map((e, i) => {
            const { event, gateway, request_id, t, attempt, ...details } = e;
            return (
              <tr key={i}>
                <td>{t.toFixed(3)}</td>
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
    </main>
  );
}
