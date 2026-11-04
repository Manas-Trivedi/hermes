# Does an auction beat a queue? Results of the Hermes experiment

## The short answer

| Question | Answer |
|---|---|
| Does the exchange finish the work faster than the alternatives? | No. Every method takes about the same total time, because the provider's rate limit is the bottleneck. |
| When every agent is honest, does the exchange beat priority scheduling with aging? | No. For the most urgent agent, priority scheduling is clearly better (P95 7 s against 18 s). The exchange ties or wins for the research agent and loses for the PR review agent. |
| When one agent lies about how urgent its work is, does the exchange hold up? | Yes. Priority scheduling is exploited. The exchange is not. This is the one clear win. |
| Is this a large, final result? | No. Three seeds, about 20 pieces of work per run, a mock provider, and four of the planned robustness checks were not run. See [What this does not show](#what-this-does-not-show). |

So the honest conclusion is narrower than the project's original claim. The auction is **not** faster than a good priority queue when everyone tells the truth. Its advantage is that urgency has to be paid for, so claiming "urgent" no longer works as a free trick.

## What was compared

Hermes sits between agents and an LLM provider. The provider allows a fixed number of calls per minute, so calls have to wait their turn. The experiment tests three ways of ordering that wait. All three used the same agents, the same work, the same fake provider and the same urgency scorer.

| Condition | How a waiting call is chosen |
|---|---|
| **FIFO** (the floor) | First come, first served. Urgency is ignored. |
| **Priority with aging** (the real baseline) | The call with the highest urgency score goes first. A waiting call gains points every second, so nothing waits forever. |
| **Exchange** (Hermes) | Every call bids for the next slot. The price comes from the same urgency score, but an agent can only bid what it can afford from a credit balance that refills at a steady rate. The highest bid wins. |

Words used below:

| Term | Meaning |
|---|---|
| **Slice** | One slot to make one call. The provider releases one every 3 seconds (20 calls a minute). |
| **P95 latency** | How long the slowest 1 in 20 calls took, from the moment the agent asked to the moment it got the answer. It describes the bad cases, not the average. |
| **Wasted retry** | A call the provider refused with a 429 ("too many requests") and that had to be sent again. |
| **Failure** | A call that was cancelled, or ended in anything but a success. |
| **Honest agent** | Declares how urgent its work really is. |
| **Inflating agent** | Declares every call as urgent and due now, whatever it is. |
| **Seed** | A number that fixes the random arrivals, so every condition sees exactly the same work. |

## The setup

| Item | Value |
|---|---|
| Agents | **Support** (customer waiting, tight deadline), **Research** (bursts of calls, medium deadline), **PR review** (nobody waiting, loose deadline) |
| Demand | About 30 calls a minute against 20 allowed, so calls always compete |
| Work per run | New work arrives for 2 minutes, then the queue drains. 17 to 20 pieces of work, which is 57 to 68 calls |
| Provider | A seeded fake that refuses any call arriving sooner than one slice after the last. Median reply time 1 second |
| Seeds | 1, 2 and 3. Each seed was run under all three conditions, once with everyone honest and once with PR review inflating |
| Priority baseline | Aging of 1 point per second, fixed before any run |
| Exchange credits | A pool of 10 credits a second, split by expected demand times business weight (support 3, research 2, PR review 1), so support gets 58%, research 26% and PR review 16%. Balances are capped at 60 seconds of refill |

That makes 18 main runs, plus 6 runs of an equal-share variant. Every run is stored in Postgres with all its events.

## Results

Numbers are means over 3 seeds. The chart shows the P95 per agent, with a line from the lowest to the highest seed.

![P95 latency per agent under each condition](p95-by-agent.svg)

### Across all calls

| Condition | Honest: finished at | Honest: P95 | Inflating: finished at | Inflating: P95 | Failures (honest, inflating) |
|---|---|---|---|---|---|
| FIFO | 192 s | 63 s | 192 s | 63 s | 0, 0 |
| Priority with aging | 192 s | 80 s | 189 s | 86 s | 0, 0.3 |
| Exchange | 188 s | 88 s | 190 s | 88 s | 0.7, 0.3 |

All three finish together, within 2% (the rate limit decides that). Across all calls, FIFO has the lowest P95. That is expected and is not a good sign for FIFO: any method that serves urgent work first makes the least urgent work wait longer, and the slowest 1 in 20 calls is mostly that least urgent work. The per-agent view below shows who is being served.

### Per agent (P95 in seconds, lower is better)

| Agent | FIFO | Priority | Exchange | FIFO | Priority | Exchange |
|---|---|---|---|---|---|---|
| | **All honest** | | | **PR review inflates** | | |
| Support (a customer waiting) | 61.5 | **7.4** | 18.0 | 61.5 | 41.7 | **15.1** |
| Research | 56.0 | 62.0 | **47.7** | 56.0 | 105.2 | **45.1** |
| PR review | **63.4** | 87.0 | 90.8 | 63.4 | **42.1** | 92.4 |

How to read it:

- **Honest case.** Priority gives support the best service by a wide margin (7.4 s against 18.0 s). It is the same in all 3 seeds. The exchange is far better than FIFO for support (18 s against 62 s). For research it has the lowest mean, but not in every seed (in seed 1, FIFO was better). PR review pays for it under both urgency-aware methods.
- **Inflating case.** When PR review lies, priority scheduling is exploited in all 3 seeds. PR review's own P95 drops from 87 s to 42 s, while support's rises from 7.4 s to 41.7 s and research's from 62 s to 105 s. Under the exchange, PR review gains nothing (91 s to 92 s) and the others are untouched (support 18.0 s to 15.1 s). Its credits run out, so claiming urgency stops working.

### Variants and checks that were run

| Check | Result |
|---|---|
| **Equal-share credits** (the pool split three ways, ignoring demand and weight) | Support is much worse (P95 42 s against 18 s) and research a little better (43 s against 48 s). The business weights are doing real work, and the credit rule is a policy that has to be chosen, not a free lunch. |
| **Before and after a bug fix** | An earlier version of the exchange released the next slice too soon after a late bid took a waiting slice, so every exchange run paid one extra wasted retry that the baselines did not. It was fixed and the exchange rerun. The effect on P95 was tiny (support 17.7 s before, 18.0 s after). The old runs are kept under the name `pre-spacing-fix`. |
| **Consistency across seeds** | For support with honest agents, priority beat the exchange and the exchange beat FIFO in all 3 seeds. With PR review inflating, the exchange beat priority for both support and research in all 3 seeds, and priority's PR review improved in all 3 while the exchange's did not. Research against FIFO is not consistent across seeds. |

## One request, step by step

A support ticket's answer in the exchange run for seed 1, all agents honest (real numbers from the stored events):

| Time | What happened |
|---|---|
| 31.2 s | The ticket's answer call arrives. Its score would put the bid near 90, but the support agent has spent most of its credits on earlier calls, so the bid is capped at **2**. |
| 31.2 s to 45.0 s | Every second the call is re-priced, and every time it can afford a little more, because credits are refilling. It is raised 8 times, to 48. |
| 45.0 s | A slice is released. This bid is now the highest, so it wins and pays **48**. |
| 45.0 s to 45.9 s | The call goes to the provider and the answer comes back. Total wait for the customer: **14.7 s**. |

This is the main reason the exchange loses to priority scheduling here. Support's share of the pool (5.8 credits a second) is smaller than what its steady stream of urgent calls would cost, so it regularly runs short. That is an explanation consistent with the numbers, not one that has been proven. Changing the pool size (see below) is the test.

## Credit pool sweep (3 seeds)

The explanation above says the exchange loses to priority scheduling because support's share of the credit pool is too small. To test it, the exchange was rerun with a pool of 20 and 40 credits a second (the original was 10), once with honest agents and once with PR review inflating, on seeds 1 to 3. Only the exchange depends on the pool, so priority and FIFO were not rerun. The numbers are P95 latency in seconds, averaged over the three seeds. Failures are the total over the three seeds (24 PR review calls and about 55 calls in all per seed).

| Case | Condition | Support | PR review | Research | Failures |
|---|---|---|---|---|---|
| Honest | fifo | 61.5 | 63.4 | 56.0 | 0 |
| Honest | priority | **7.4** | 87.0 | 62.0 | 0 |
| Honest | exchange, pool 10 | 18.0 | 91.7 | 47.7 | 2 |
| Honest | exchange, pool 20 | 8.3 | 102.9 | 41.9 | 3 |
| Honest | exchange, pool 40 | 8.3 | 102.4 | 41.9 | 2 |
| PR review inflates | fifo | 61.5 | 63.4 | 56.0 | 0 |
| PR review inflates | priority | 41.7 | 42.1 | 105.5 | 1 |
| PR review inflates | exchange, pool 10 | 15.1 | 92.9 | 45.1 | 1 |
| PR review inflates | exchange, pool 20 | 9.2 | 92.0 | 57.0 | 0 |
| PR review inflates | exchange, pool 40 | 13.4 | 82.3 | 82.9 | 1 |

| What it shows | Detail |
|---|---|
| The small pool was the main cause | Going from 10 to 20 cuts support from 18.0 s to 8.3 s with honest agents, close to priority's 7.4 s. A pool of 40 adds nothing. |
| A bigger pool weakens the protection | At 40, research under inflation waits 82.9 s, close to priority's 105.5 s, and PR review gains more from lying (82.3 s against 92.0 s at 20). Credits stop running out, so the exchange starts to behave like a priority queue. |
| It is a trade-off | A small pool protects other agents from a liar but slows the urgent agent. A large pool does the opposite. 20 is the middle point on these seeds, and it still beats priority scheduling under inflation (support 9.2 s against 41.7 s). |
| The cost lands on PR review | PR review, the lowest-weighted agent, waits longest with honest agents (102.9 s against 87.0 s under priority). All failures here are the same kind: a PR review call that lost every auction and was cancelled by the agent after its own 120 s timeout, never sent. They are starvation of the lowest bidder, which is accepted by design until aging is strong enough. The counts (0 to 3) are too small to rank the pool sizes on failures. |

**Limits.** Three seeds, and support makes only 22 calls per run, so its P95 is close to its second-slowest call. Pool 20 was picked after seeing seed 1, and seeds 2 and 3 agreed, which is the check the choice needed, but the pool and the weights are still a policy that was chosen, not a free result. The refill rate and the cap were not swept.

## What can go wrong with this result

| Risk | Detail |
|---|---|
| **Tiny sample** | 3 seeds and about 20 pieces of work per run. Orderings were consistent, but the exact numbers (and especially the small gaps, such as research 47.7 s against 56.0 s) should not be trusted to the second. |
| **Fake provider** | It enforces exact spacing between calls. Real providers use per-minute windows and variable latency. |
| **Tuned by one person, once** | The aging rate (1 per second) and the credit pool (10 a second) were fixed before the main runs, as planned, and not adjusted afterwards. The pool was swept later (see the credit pool sweep), with pool 20 chosen after seeing seed 1 and confirmed on seeds 2 and 3; the main tables above still use 10. The aging rate was never swept, so a different one could make priority scheduling look better or worse. |
| **Short runs** | A 2-minute arrival window. Credit balances start full, which helps every agent early on. A longer run would test the regeneration rule harder. |
| **A found bug** | One bug that favoured the baselines was found and fixed during the sanity check (see above). There may be others that favour either side. |
| **A pause during the run** | The last run took 13 minutes of wall-clock time instead of 3, most likely because the computer went to sleep. The experiment's clocks do not count sleep, so its numbers should be unaffected, but the run's stored start and finish times are not meaningful. |

## What this does not show

These checks were planned and **were not run**, because of time:

| Not done | Why it matters |
|---|---|
| Sweep the priority baseline's aging rate | The baseline might be weaker or stronger than shown. |
| Sweep the credit refill rate and cap | The pool size was swept (see above); how the pool is split and how large balances can grow was not. |
| Vary the provider's rate limit | The comparison was run at one level of overload. |
| More seeds | Needed for any claim stronger than "consistent in these three". |

The commands to run them are in the README: the runner takes `--aging-rate`, `--pool`, `--limit`, `--equal-share` and `--conditions`, so each sweep is one command per value.

## Reproducing it

```bash
docker compose up -d                       # Postgres, and the results server on port 8766
uv run python -m experiments.runner --database postgresql://postgres:hermes@localhost:5434/hermes --name main --seeds 1,2,3
uv run python -m experiments.report --database postgresql://postgres:hermes@localhost:5434/hermes
uv run python -m experiments.chart  --database postgresql://postgres:hermes@localhost:5434/hermes --name main --out docs/p95-by-agent.svg
```

A full run takes about 3 minutes per condition per seed and variant, so the 18 main runs take about an hour.
