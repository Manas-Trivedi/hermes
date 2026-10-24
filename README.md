<pre align="center">
██╗  ██╗███████╗██████╗ ███╗   ███╗███████╗███████╗
██║  ██║██╔════╝██╔══██╗████╗ ████║██╔════╝██╔════╝
███████║█████╗  ██████╔╝██╔████╔██║█████╗  ███████╗
██╔══██║██╔══╝  ██╔══██╗██║╚██╔╝██║██╔══╝  ╚════██║
██║  ██║███████╗██║  ██║██║ ╚═╝ ██║███████╗███████║
╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝╚═╝     ╚═╝╚══════╝╚══════╝
</pre>

<p align="center">
  <b>A real-time auction market for scarce LLM capacity.</b><br>
  Agents bid for compute by how urgent their work actually is, not by when they showed up.
</p>

<p align="center">
  <img alt="status" src="https://img.shields.io/badge/status-early%20development-orange">
  <img alt="C++23" src="https://img.shields.io/badge/C%2B%2B-23-blue">
  <img alt="python" src="https://img.shields.io/badge/python-3.12%2B-blue">
</p>

---

## Why

Every agentic system shares one scarce resource: LLM API rate limits, GPU minutes, a connection pool. Today that resource is handed out first-come-first-served, so a support ticket a customer is staring at waits behind a background code review that nobody is watching.

Hermes treats capacity as an asset and runs an exchange for it. Throttled capacity is released in fixed time slices. Agents bid for the next slice with a price derived from real urgency: deadline slack, whether a user is waiting, how long the task has already queued. The same price-time-priority matching used by stock exchanges clears the book, and a gateway only forwards an LLM call once that call has won a slice.

The claim to prove, with numbers: **market-based allocation beats naive rate limiting** on completion time, tail latency, failures and wasted retries, on identical workloads.

## How it works

1. A capacity scheduler releases one slice at the real throttle rate and offers it for sale. An unsold slice expires.
2. Each agent task is priced by an interpretable urgency model and enters the book as a bid.
3. The matching engine gives the slice to the highest bid. Ties go to the earliest arrival.
4. The gateway forwards the winning call to the model and holds back everything else.
5. A live dashboard shows the book, the fills and each agent's queue, and an experiment runner replays one workload under FIFO and under the exchange to compare the two.

## Status

Hermes is being built in the open, one small step at a time.

| Stage | What | State |
|---|---|---|
| Matching engine | Price-time priority order book, trade reporting, hardened input handling | In progress |
| Engine interface and scheduler | Drive the book from other processes, release capacity slices | Planned |
| Throttled gateway | Mock backend, FIFO baseline, exchange-gated forwarding | Planned |
| Urgency model | Explainable bid pricing, regenerating credit budgets | Planned |
| Bidder agents | PR review, support triage, research synthesis | Planned |
| Persistence and live feed | Event storage and a WebSocket stream | Planned |
| Dashboard | Live order book, fills, naive vs exchange comparison | Planned |
| Experiment | Same workload, two allocation strategies, published results | Planned |

No benchmark numbers yet. They will appear here once the experiment has actually been run.

## Getting started

Hermes is not usable end to end yet. The matching engine builds and its tests run today.

**Requirements**

- A C++23 compiler (recent Clang or GCC)
- CMake 3.10 or newer
- Internet access on the first build, to fetch GoogleTest

**Build and test the engine**

```bash
cd engine
cmake -S . -B build
cmake --build build
./build/matcha_tests
```

**Play with the book interactively**

```bash
./build/matcha
```

You enter orders on stdin (id, type, side, price, quantity) and the book is printed at the end.

## Matching rules

- Buyers match the lowest asking price first, sellers match the highest bid first.
- Orders at the same price fill in arrival order.
- Partial fills are supported. An unfilled limit remainder rests in the book.
- A market order never rests.
- Resting orders can be cancelled by id.

## Roadmap

Beyond the core experiment, ideas on the list: reselling an unused slice, separate capacity pools for cheap and expensive models, a gateway circuit breaker, and replaying recorded order flow at different throttle settings.

## Credits

The matching engine started life as [Matcha](https://github.com/manas-trivedi/matcha), a single-instrument order book in C++.
