import { bidsInOrder, type Book } from "./book";

export function OrderBook({ book }: { book: Book }) {
  const bids = bidsInOrder(book);
  return (
    <section>
      <h2>Order book</h2>
      <p>
        last clearing price: <b>{book.lastPrice ?? "none yet"}</b> · {bids.length} resting bids
      </p>
      <table>
        <thead>
          <tr>
            <th align="left">price</th>
            <th align="left">request</th>
            <th align="left">waited (s)</th>
          </tr>
        </thead>
        <tbody>
          {bids.map((b) => (
            <tr key={b.id}>
              <td>{b.price}</td>
              <td>{b.id}</td>
              <td>{(book.now - b.since).toFixed(1)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
