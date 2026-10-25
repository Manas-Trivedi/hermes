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

The claim to prove, with numbers: **market-based allocation beats both naive rate limiting and priority scheduling with aging** on completion time, tail latency, failures and wasted retries, on identical workloads.

## What it will be

The goal is a service you can deploy, not a demo. Hermes will be a drop-in proxy that speaks the OpenAI chat API and sits in front of your LLM provider. Point your agents' base URL at it and nothing else in the agents changes. It will run from a Docker image, configured by a file, with API keys and credit budgets per team. This is the target and none of the service layer is built yet; the status table below says what exists.

## How it works

1. A capacity scheduler releases one slice at the real throttle rate and offers it for sale. An unsold slice expires.
2. Each agent task is priced by an interpretable urgency model and enters the book as a bid.
3. The matching engine gives the slice to the highest bid. Ties go to the earliest arrival.
4. The gateway forwards the winning call to the model and holds back everything else.
5. A live dashboard shows the book, the fills and each agent's queue, and an experiment runner replays one workload under FIFO, under priority scheduling with aging, and under the exchange to compare them.

## Status

Hermes is being built in the open, one small step at a time.

| Stage | What | State |
|---|---|---|
| Matching engine | Price-time priority order book with trade reporting and input rejection | Done |
| Engine interface and scheduler | Drive the book from other processes, release capacity slices | Done |
| Throttled gateway | Mock backend, FIFO and priority baselines, exchange-gated forwarding | In progress (mock backend done) |
| Urgency model | Explainable bid pricing, regenerating credit budgets | Planned |
| Bidder agents | PR review, support triage, research synthesis | Planned |
| Persistence and live feed | Event storage and a WebSocket stream | Planned |
| Dashboard | Live order book, fills, FIFO vs priority vs exchange comparison | Planned |
| Experiment | Same workload, three allocation strategies, published results | Planned |
| Deployable service | OpenAI-compatible proxy, token-weighted capacity, API keys and budgets per team, restart safety, Docker image | Planned |

No benchmark numbers yet. They will appear here once the experiment has actually been run.

## Getting started

Hermes is not usable end to end yet. The matching engine, its Python client and the capacity scheduler run today.

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

**Test the Python client**

Needs [uv](https://docs.astral.sh/uv/) and the engine built as above.

```bash
uv run pytest
```

**Watch the market run**

A script releases capacity slices at a fixed rate and throws random bids at them for ten seconds. It prints every release, bid, fill and expiry, then checks that nothing was lost or double counted.

```bash
uv run python -m experiments.synthetic_bidders
```

**Drive the book from the command line**

```bash
printf 'SELL 1 100 1\nBUY 8 105 1\nBOOK\n' | ./build/matcha --arena 1000
```

The engine reads one command per line on stdin and writes one reply per command on stdout. It prints `READY` when it is up, and exits when stdin closes. The full command set and reply format are documented in the protocol notes under the engine directory.

## Matching rules

- Buyers match the lowest asking price first, sellers match the highest bid first.
- Orders at the same price fill in arrival order.
- Partial fills are supported. An unfilled limit remainder rests in the book.
- A market order never rests.
- Trades execute at the resting order's price.
- Resting orders can be cancelled by id.
- An order is rejected if its id is already resting, if there is no room left to rest it, or, for a cancel, if the id is unknown.

## Roadmap

Beyond the core experiment, ideas on the list: reselling an unused slice, separate capacity pools for cheap and expensive models, a gateway circuit breaker, and replaying recorded order flow at different throttle settings.

## Credits

The matching engine started life as [Matcha](https://github.com/manas-trivedi/matcha), a single-instrument order book in C++.
