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
| Throttled gateway | Mock backend, FIFO and priority baselines, exchange-gated forwarding, shared event log | Done |
| Urgency model | Explainable bid pricing and aging of waiting bids | Done |
| Credit budgets | Regenerating per-agent balances that cap bids | Done |
| Bidder agents | PR review, support triage, research synthesis, and a seeded workload that drives them | Done |
| Persistence and live feed | Event storage and a WebSocket stream | Planned |
| Dashboard | Live order book, fills, FIFO vs priority vs exchange comparison | Planned |
| Experiment | Same workload, three allocation strategies, published results | Planned |
| Deployable service | OpenAI-compatible proxy, token-weighted capacity, API keys and budgets per team, restart safety, Docker image | Planned |

No benchmark numbers yet. They will appear here once the experiment has actually been run.

## Getting started

Hermes is not usable end to end yet. The matching engine, its Python client, the capacity scheduler, the gateways, the urgency scorer, credit budgets and the three agents with their seeded workload run today. The experiment runner and the dashboard do not exist yet.

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

## How a bid is priced

A task carries its tenant, when it was queued, an optional deadline, whether a person is waiting on it, and whether it is one call of a bulk job. The scorer turns these into a price made of named parts, and the price is exactly their sum:

| Part | Effect |
|---|---|
| base | Every task starts here |
| user facing | Adds points when a person is waiting |
| batched | Takes points off calls of a bulk job, so interactive work goes first |
| deadline | Rises from nothing to its full weight as the deadline gets closer, and stays there once it has passed |
| wait | Grows with time spent queued, so old work is not starved |

So when one task outbids another, the difference between their parts says why. A waiting bid is re-priced as time passes: if it now scores higher, it is cancelled and placed again at the new price. A bid is only ever raised. The weights are operator settings, and the current values are placeholders.

## The agents

Three agents make the calls. They send them through whichever gateway is under test, so the same agents run under FIFO, priority scheduling and the exchange.

| Agent | Work | Urgency it declares |
|---|---|---|
| PR review | One call per changed file, all at once, then a summary | Nobody is waiting, loose deadline |
| Support | Triage a ticket, then answer it | A customer is waiting, tight deadline |
| Research | A burst of one call per paper, then a synthesis | Nobody is waiting, medium deadline |

An agent whose call runs out of patience cancels it, and a stage that fails stops the rest of that piece of work so no capacity is spent on a result nobody can use. Any agent can be made dishonest, declaring every call as urgent and due now, to test whether the exchange resists inflated priorities.

The workload is generated from a seed: the same seed gives the same arrivals and the same work, and changing one agent's rate leaves the other two agents' work exactly as it was. The mock backend ignores what a prompt says, so prompts are filler; what the experiment varies is when each call arrives and how urgent it is.

## Credit budgets

Without a cost for urgency, every agent would bid its maximum. So each agent has a balance of credits that refills at a steady rate and stops growing at a cap, which lets unused credits carry over without piling up forever.

- A bid can offer no more than the agent can afford, and there is no overdraft. An agent that cannot afford even the minimum price waits, and can still cancel, until its credits refill.
- A bid holds its credits while it waits, so one balance cannot back many bids at once. A cancelled bid gives them back.
- Winning spends the price actually paid. If the backend rejects a call that already won, the retry pays again.
- Refill rates are set by the operator, never by the agents: each agent gets a share of a total pool in proportion to its expected demand times its business weight. The demands, the weights, the pool and the cap are all settings. By default every agent counts the same and the pool matches the experiment's expected load, and they are meant to be set before a run.

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
