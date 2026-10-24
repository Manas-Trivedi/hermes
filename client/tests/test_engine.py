import os
import pytest

from client import (
    ArenaFull,
    BadCommand,
    BookEntry,
    DuplicateId,
    Engine,
    EngineDied,
    Trade,
    UnknownId,
)
from client.engine import DEFAULT_BINARY


BINARY = os.environ.get("HERMES_ENGINE") or DEFAULT_BINARY
pytestmark = pytest.mark.skipif(not os.path.exists(BINARY), reason=f"engine binary not built: {BINARY}")


@pytest.fixture
def engine():
    with Engine(arena=2) as e:
        yield e


def test_crossing_order_returns_parsed_trades(engine):
    assert engine.sell(1, 100, 2) == []
    assert engine.buy(8, 105, 1) == [Trade(taker_id=8, maker_id=1, price=100, qty=1)]
    assert engine.market_buy(9, 1) == [Trade(9, 1, 100, 1)]
    assert engine.market_sell(10, 1) == []


def test_engine_errors_raise_matching_exceptions(engine):
    engine.buy(1, 100, 1)
    with pytest.raises(DuplicateId):
        engine.buy(1, 100, 1)
    engine.buy(2, 100, 1)
    with pytest.raises(ArenaFull):
        engine.buy(3, 100, 1)
    engine.cancel(1)
    with pytest.raises(UnknownId):
        engine.cancel(1)
    with pytest.raises(BadCommand):
        engine.buy(4, 0, 1)
    # still usable after errors
    assert engine.book() == [BookEntry("BID", 100, 1, 2)]


def test_non_integers_cannot_inject_commands(engine):
    with pytest.raises(TypeError):
        engine.buy("1 100 1\nCANCEL 1", 100, 1)
    assert engine.book() == []


def test_book_lists_bids_then_asks(engine):
    engine.sell(1, 110, 1)
    engine.buy(2, 90, 3)
    assert engine.book() == [BookEntry("BID", 90, 3, 2), BookEntry("ASK", 110, 1, 1)]


def test_dead_engine_raises_instead_of_hanging(engine):
    engine._proc.kill()
    engine._proc.wait()
    with pytest.raises(EngineDied):
        engine.book()


def test_context_manager_reaps_the_process():
    with Engine(arena=1) as e:
        proc = e._proc
    assert proc.poll() == 0
