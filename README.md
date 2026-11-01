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
| Persistence and live feed | Postgres storage of every run, request, bid and fill, and a live WebSocket stream of gateway events | Done |
| Dashboard | Live order book, fills, per-agent request timelines, and a FIFO vs priority vs exchange comparison of stored runs | Done |
| Experiment | Same workload, three allocation strategies, published results | Runner built, no results yet |
| Deployable service | OpenAI-compatible proxy, token-weighted capacity, API keys and budgets per team, restart safety, Docker image | Planned |

No benchmark numbers yet. They will appear here once the experiment has actually been run.

## Getting started

Hermes is not usable end to end yet. The matching engine, its Python client, the capacity scheduler, the gateways, the urgency scorer, credit budgets and the three agents with their seeded workload run today. Gateway events can be stored in Postgres and streamed over WebSocket. The dashboard shows a run live and compares stored runs. An experiment runner plays the workload under all three conditions and stores the runs; the final metrics, sweeps and write-up are still to come.

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

**Test the Python code**

Needs [uv](https://docs.astral.sh/uv/) and the engine built as above.

```bash
uv run pytest
```

The tests that touch Postgres run only when `HERMES_TEST_DATABASE_URL` points at a database, and are skipped otherwise. Each test works in its own throwaway schema, so the development database below can be reused:

```bash
export HERMES_TEST_DATABASE_URL=postgresql://postgres:hermes@localhost:5434/hermes
uv run pytest
```

**Watch the market run**

A script releases capacity slices at a fixed rate and throws random bids at them for ten seconds. It prints every release, bid, fill and expiry, then checks that nothing was lost or double counted.

```bash
uv run python -m experiments.synthetic_bidders
```

**Watch a mock run on the dashboard**

The demo plays the three agents' seeded workload through one gateway against the mock backend, and streams every event to the dashboard. It waits for a dashboard to connect before it starts, so the first bid is not missed.

```bash
uv run python -m experiments.demo --gateway exchange --duration 120 --limit 20
cd dashboard && npm install && npm run dev
```

Open the page the dev server prints. It shows:

| Panel | What it shows |
|---|---|
| Order book | Bids waiting for a slice, best price first, and the price the last fill paid |
| Fills | The latest slices won, who won them and what they paid |
| Agent timelines | One row per request over the last minute: grey while it waits for a slice, blue while the backend has it, a cross for each rejection (429) |
| Comparison | Stored runs side by side: completion time, P95 latency, failures and wasted retries for FIFO, priority and exchange |

The workload asks for about 27 calls a minute, so a limit of 20 makes the agents compete and shows bids being raised and rejected. `--gateway fifo` and `--gateway priority` run the same work under the other two conditions.

The comparison reads runs stored in Postgres. A development stack with Postgres (schema already applied) and the results server that the dashboard reads comes up with one command. It needs Docker.

```bash
docker compose up -d
uv run python -m experiments.demo --gateway fifo --database postgresql://postgres:hermes@localhost:5434/hermes
```

Postgres is then on port 5434 and the results server on port 8766, which is where the dashboard looks. The engine, the demo and the experiment runner keep running on your machine and write to that database; only Postgres and the results server run in containers. `docker compose down` stops them and keeps the data, and `docker compose down -v` also deletes it. Run the demo under each condition (`--gateway fifo`, `priority`, `exchange`), and reload the comparison.

To use your own Postgres instead, apply the schema once and run the results server by hand:

```bash
uv run python -c "from store import connect, apply_schema; apply_schema(connect('<url>'))"
uv run python -m store.api --database <url>
```

The results server also breaks each run down per agent (`/agents`): the same five numbers for PR review, support and research, so you can see who a condition helps and who it hurts. Only runs that finished are shown, so a run that crashed halfway never passes for a result. A failure is a request that was cancelled or that ended on anything but a 200. The comparison treats the seeds of one experiment as repeats: each bar is the mean over the runs of that condition, with a line from the lowest to the highest, and a per-agent table sits under it. A single demo run shows as one run with no range.

**Run the experiment**

The runner plays the same seeded workload through FIFO, priority scheduling with aging and the exchange (with credit budgets), one after the other, and stores every run in Postgres. For each seed it does this twice: once with all agents honest, and once with the PR review agent declaring every call as urgent and due now.

```bash
uv run python -m experiments.runner --database postgresql://postgres:hermes@localhost:5434/hermes --seeds 1,2,3
```

Each seed and variant is stored as its own experiment, so the dashboard's comparison shows the three conditions side by side. Runs go one at a time, because overlapping runs would be measuring each other. A run that fails stays unfinished and the runner stops with the error. The settings that matter (backend limit, priority aging rate, credit pool, and `--equal-share` to split the pool equally instead of by demand times weight) are flags, and they are recorded with every run. `--conditions` runs only some conditions, since a sweep of the aging rate only affects priority and a sweep of the pool only affects the exchange. A full default run is slow: each run lasts a couple of minutes, and a seed makes six of them.

To read the stored results as tables instead (mean over seeds with the range, a table per agent, and how often the exchange beat each baseline seed by seed):

```bash
uv run python -m experiments.report --database postgresql://postgres:hermes@localhost:5434/hermes
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

## Token limits

Providers cap tokens per minute as well as requests per minute. The exchange gateway takes an optional tokens-per-minute limit. A slice stays one request, but each request that wins is charged its estimated tokens (its prompt at about four characters a token, plus the most it may generate), and the next slice is held back until those tokens are repaid at the token rate. So the release rate follows whichever limit is stricter, and a large request delays the line behind it instead of paying a bigger price. The estimate is a budget, not a count; correcting it with the usage the provider reports comes with the OpenAI-compatible surface. Without a token limit nothing changes.

## The proxy

`gateway.proxy` is the drop-in endpoint. Agents point their base URL at it and keep calling `POST /v1/chat/completions`, streamed or not. Each call is priced (prompt size, `max_tokens`, optional urgency headers), waits in the exchange until it wins a slice, and only then goes to the provider. The reply is passed back byte for byte.

```bash
uv run python -m gateway.proxy --config hermes.toml
```

The config file (TOML) holds everything an operator sets:

```toml
[upstream]
url = "https://api.openai.com/v1/chat/completions"
api_key_env = "OPENAI_API_KEY"   # the environment variable holding the provider's key

[limits]
requests_per_minute = 60
tokens_per_minute = 90000        # optional

[[tenants]]
id = "acme"
share = 2.0                      # its slice of the credit pool, relative to the other tenants
api_keys = ["sk-hermes-..."]
```

With tenants listed, every request must carry `Authorization: Bearer <api key>` of one of them (otherwise 401). The key picks the tenant. Each tenant has its own credit balance, refilled in proportion to its share, so one team cannot spend another's urgency. The tenant is on every event the request produces and is stored with it. The client's key is never sent to the provider; the proxy uses its own. Without any tenants the proxy is open and has no budgets, which is for local use. Keys are held only as hashes once loaded. The other settings (`[server]`, `[credits]`, `default_max_tokens`) are described at the top of the config module.

| Header | Meaning |
|---|---|
| `X-Hermes-User-Facing: true` | A person is waiting on the answer |
| `X-Hermes-Deadline-Seconds: 30` | When the answer is needed, from now |
| `X-Hermes-Batch: <id>` | One call of a bulk job |

All are optional and are removed before the call goes to the provider. A provider 429 is retried behind the scenes a few times (`max_rate_limit_retries`, default 3), then the client gets the provider's own 429 and body, so a quota that cannot recover does not loop forever. A request that cannot be priced gets a 400, an unreachable provider a 502 and a provider that stays silent past `timeout_seconds` a 504, all in OpenAI's error format. With tenants, a provider 401 or 403 means the proxy's own key is wrong, so the client gets a 502 instead. A client that hangs up while its call waits has its bid withdrawn, and one that leaves mid-reply stops the upstream read.

## Health and metrics

`GET /health` answers `ok`, `degraded` (still serving, but events are not being stored or credit balances not saved) or, with a 503, `down` (the exchange has stopped). `GET /metrics` is Prometheus text: requests, fills, provider 429s, cancels and results by status, all per tenant; the latest clearing price; queue depth and credit balance per tenant; the adaptive rate scale; and whether storage is failing. Counters come from the same event log that is stored, so the two agree. Because the page names the tenants and their traffic, setting `metrics_token_env` in the `[server]` section of the config makes it require that token as a bearer token. `/health` carries nothing sensitive and is always open.

## Restarts

With a `[database]` in the config (a Postgres URL in an environment variable), the proxy stores every event, and saves each tenant's credit balance every few seconds and on shutdown. The next start picks the balances up, and they keep regenerating for the time the proxy was down, so restarting does not refill anyone's credits. The order book is not saved: it starts empty. On a clean shutdown, calls still waiting for a slice get a 503 with `Retry-After` at once, and calls already out are given time to finish. After a crash, the requests the dead process left open are marked cancelled the next time it starts. If a balance save fails it is logged and retried; a crash can lose at most the last few seconds of spending. Run one proxy process per database: the book lives in memory, and so does the cleanup that assumes nobody else is writing.

## When the provider is stricter than you thought

Provider limits are not always known, and they move. With `adaptive = true` (the proxy's default) every real 429 from the provider halves the release rate, at most once per interval so one burst of limiting counts once, and holds releases for its `Retry-After`. Each call that gets through earns back 2% of the configured rate, up to the configured rate, and the rate never falls below a tenth of it. It is the additive-increase, multiplicative-decrease rule TCP uses: the limit is found by being rejected now and then, and the slow climb keeps that rare. In a test where the configured limit was five times the provider's, eight calls cost 32 wasted retries with a fixed rate and 3 with the adaptive one. The experiment gateways are not adaptive, so the results do not depend on it.

## Deploying

The `deploy` directory has what a team needs to run the proxy with its own Postgres. It needs Docker.

```bash
cd deploy
cp hermes.example.toml hermes.toml   # set your provider's limits and one block per team, with new keys
cp .env.example .env                 # the provider key, a metrics token and a database password
docker compose up -d --build
```

Point your agents' base URL at `http://<host>:8080/v1` and give each team its own `Bearer` key. The first build compiles the matching engine and fetches its test library, so it needs network and takes a few minutes. The Postgres schema is applied by the proxy itself at every start.

| Setting | Where | What it does |
|---|---|---|
| Provider limits | `[limits]` in `hermes.toml` | What your account is allowed. The proxy slows itself down if the provider says less |
| Teams | `[[tenants]]` | A name, a share of the credit pool, and the keys that identify its calls |
| Provider key, metrics token, database | `.env` | Secrets, kept out of the config file |
| `HERMES_PORT` | `.env` | The port the proxy is published on, 8080 by default |

Check it with `curl localhost:8080/health`. To stop it without dropping work, use `docker compose stop`: calls still waiting for a slice get a 503 with `Retry-After`, and calls already out get up to a minute to finish. Run one proxy per database. The dashboard is not part of the image yet.

## Recording and watching a run

Every gateway reports each step of a request's life (request, bid, fill, forward, rejected, result, cancelled) as an event. Two listeners can be attached to any gateway, on their own or together:

| Listener | What it does |
|---|---|
| Event writer | Stores events in Postgres: one row per request with its outcome and its count of 429s, one row per bid or raise, one row per fill. Rows belong to an experiment run, which records the condition, the seed and the settings. |
| Live feed | Sends each event as a JSON message to every connected WebSocket client the moment it happens. A client sees only events from when it connects, and one that falls too far behind is disconnected rather than slowing the gateway. |

A gateway never waits on either. The writer queues events and writes them in batches from its own thread. If a write fails, the writer stops and raises when it is closed, so a run cannot report success while its events were lost.

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
