"""Python client for the matching engine's line protocol (engine/PROTOCOL.md)."""

import operator
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DEFAULT_BINARY = Path(__file__).resolve().parent.parent / "engine" / "build" / "matcha"

class EngineError(Exception):
    """Base class for everything the client raises."""


class DuplicateId(EngineError):
    """An order with this id is already resting."""


class ArenaFull(EngineError):
    """No room to rest the order; it made no trades."""


class UnknownId(EngineError):
    """Cancel target is not resting: filled, cancelled already, or never existed."""


class BadCommand(EngineError):
    """The engine rejected the line as malformed."""


class EngineDied(EngineError):
    """The engine process exited or closed its pipes."""


_ERRORS = {
    "DUPLICATE_ID": DuplicateId,
    "ARENA_FULL": ArenaFull,
    "UNKNOWN_ID": UnknownId,
    "BAD_COMMAND": BadCommand,
}


@dataclass(frozen=True)
class Trade:
    taker_id: int
    maker_id: int
    price: int
    qty: int


@dataclass(frozen=True)
class BookEntry:
    side: str  # "BID" or "ASK"
    price: int
    qty: int
    id: int


def _num(value) -> int:
    # operator.index rejects strings and floats, so a caller cannot smuggle a
    # space or newline into the line and inject a second command.
    return operator.index(value)


class Engine:
    """One engine subprocess. Not thread safe: callers serialize their calls."""

    def __init__(self, arena: int, binary: str | os.PathLike | None = None):
        binary = binary or os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
        self._proc = subprocess.Popen(
            [str(binary), "--arena", str(_num(arena))],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            if self._readline() != "READY":
                raise EngineError("engine did not start with READY")
        except EngineError:
            self.close()
            raise

    def __enter__(self) -> "Engine":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def close(self) -> None:
        """Close stdin so the engine exits, then reap it. Safe to call twice."""
        if self._proc.stdin and not self._proc.stdin.closed:
            try:
                self._proc.stdin.close()
            except BrokenPipeError:
                pass
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self._proc.wait()
        if self._proc.stdout:
            self._proc.stdout.close()

    def buy(self, id: int, price: int, qty: int) -> list[Trade]:
        return self._order(f"BUY {_num(id)} {_num(price)} {_num(qty)}")

    def sell(self, id: int, price: int, qty: int) -> list[Trade]:
        return self._order(f"SELL {_num(id)} {_num(price)} {_num(qty)}")

    def market_buy(self, id: int, qty: int) -> list[Trade]:
        return self._order(f"MBUY {_num(id)} {_num(qty)}")

    def market_sell(self, id: int, qty: int) -> list[Trade]:
        return self._order(f"MSELL {_num(id)} {_num(qty)}")

    def cancel(self, id: int) -> None:
        self._command(f"CANCEL {_num(id)}")

    def book(self) -> list[BookEntry]:
        entries = []
        for line in self._command("BOOK"):
            side, price, qty, id = line.split()
            entries.append(BookEntry(side, int(price), int(qty), int(id)))
        return entries

    def _order(self, line: str) -> list[Trade]:
        trades = []
        for reply in self._command(line):
            tag, *fields = reply.split()
            if tag != "TRADE" or len(fields) != 4:
                raise EngineError(f"unexpected trade line: {reply!r}")
            trades.append(Trade(*map(int, fields)))
        return trades

    def _command(self, line: str) -> list[str]:
        """Send one line; return the n lines that follow an `OK n` header."""
        try:
            self._proc.stdin.write(line + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, ValueError) as e:
            raise EngineDied("engine is not accepting commands") from e
        header = self._readline()
        if header.startswith("ERR "):
            code = header[4:]
            raise _ERRORS.get(code, EngineError)(code)
        tag, _, count = header.partition(" ")
        if tag != "OK" or not count.isdigit():
            raise EngineError(f"unexpected reply header: {header!r}")
        return [self._readline() for _ in range(int(count))]

    def _readline(self) -> str:
        try:
            line = self._proc.stdout.readline()
        except ValueError as e:  # stdout already closed
            raise EngineDied("engine output is closed") from e
        if not line:
            raise EngineDied("engine closed its output")
        return line.rstrip("\n")
