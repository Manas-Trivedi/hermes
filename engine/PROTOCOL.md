# Engine wire protocol

The engine is driven over stdin and stdout by a single client that spawns it as a subprocess. The protocol is line based text. One command per line in, one reply per command out, in order. Closing stdin shuts the engine down.

## Conventions

- Lines end with `\n`. Fields are separated by exactly one space. Commands are upper case and case sensitive.
- Numbers are unsigned decimal integers that fit in 64 bits. No sign, no leading `+`, no decimal point. Prices are integer ticks.
- A line is at most 128 bytes and has at most 4 fields. Longer input is rejected with `ERR BAD_COMMAND`.
- Order ids are chosen by the client and must be unique among resting orders. Bids and slices share one id space. By convention the capacity scheduler numbers its slices from 2^32 upwards, so bidders must use ids below that. The engine does not enforce this.
- Price and quantity must be at least 1. The server enforces this; the matching core does not.
- stderr is for diagnostics only and is never part of the protocol.

## Startup

The engine takes the arena size (the maximum number of resting orders) as a command line flag. Once it is ready it prints a single line:

```
READY
```

The client must wait for it before sending the first command.

## Commands

| Command | Meaning |
| --- | --- |
| `BUY <id> <price> <qty>` | Limit buy. Matches against asks at or below `price`; any remainder rests. |
| `SELL <id> <price> <qty>` | Limit sell. Matches against bids at or above `price`; any remainder rests. |
| `MBUY <id> <qty>` | Market buy. Matches what it can; the remainder is dropped, never rested. |
| `MSELL <id> <qty>` | Market sell. Same as `MBUY` on the other side. |
| `CANCEL <id>` | Remove a resting order. |
| `BOOK` | Debug dump of every resting order. |

Matching is price-time priority. Each trade executes at the price of the resting (maker) order.

## Replies

Every command gets exactly one reply, which is either an `OK` header followed by that many lines, or a single `ERR` line with nothing after it.

```
OK <n>
<n lines>
```

```
ERR <CODE>
```

The client reads one line, and for `OK` reads exactly `n` more lines. It never has to scan for a terminator.

### Trades

`BUY`, `SELL`, `MBUY` and `MSELL` reply `OK <n>` followed by `n` trade lines, in the order they executed. `n` is 0 when nothing matched.

```
TRADE <taker_id> <maker_id> <price> <qty>
```

The taker is the order just submitted and the maker is the order that was resting. This is how the client learns about fills, including fills of its own earlier resting orders: the maker id says whose order it was. The engine never sends anything unprompted.

The reply does not say how much of a limit order was left resting. The client works it out as the order's quantity minus the sum of the trade quantities.

### Cancel

`CANCEL` replies `OK 0` if the order was resting and removed. If the order is not resting, because it was already filled, already cancelled or never existed, it replies `ERR UNKNOWN_ID`. A client that cancels an expiring slice should treat this as "it was filled first", not as a failure. The engine is single threaded, so there is no race: whichever command arrived first wins.

### Book

`BOOK` replies `OK <n>` followed by `n` lines, one per resting order:

```
BID <price> <qty> <id>
ASK <price> <qty> <id>
```

All bids come first, then all asks. Within each side, orders are listed best price first, and in time priority within a price. This command exists for debugging and tests, not for the hot path.

### Errors

| Code | When |
| --- | --- |
| `DUPLICATE_ID` | An order with this id is already resting. Nothing happened. |
| `ARENA_FULL` | No room to rest the remainder. The order made no trades. |
| `UNKNOWN_ID` | `CANCEL` of an id that is not resting. |
| `BAD_COMMAND` | Unknown command, wrong number of fields, a non-number, a zero price or quantity, a number over 64 bits, or an over-long line. Nothing happened. |

An error never ends the session. After any `ERR` the engine is ready for the next line.

## Example

Client lines are prefixed `>`, engine lines `<`.

```
< READY
> SELL 1 100 1
< OK 0
> BUY 7 90 1
< OK 0
> BUY 8 105 1
< OK 1
< TRADE 8 1 100 1
> CANCEL 1
< ERR UNKNOWN_ID
> BOOK
< OK 1
< BID 90 1 7
> BUY 7 95 1
< ERR DUPLICATE_ID
> BUY 9 x 1
< ERR BAD_COMMAND
```

The slice (id 1) rests at 100. A low bid rests behind it. Bid 8 crosses at the slice's price, 100, and trades. The scheduler's later cancel of the slice finds it already gone.
