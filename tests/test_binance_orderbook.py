import json
import time
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import MarketTick, OrderBookTick
from cex_dex_arbitrage.sources.binance_orderbook import BinanceOrderbookSource


SAMPLE_PAYLOAD = {
    "e": "bookTicker",
    "u": 400900217,
    "E": 1568014460893,
    "T": 1568014460891,
    "s": "BNBUSDT",
    "b": "25.35190000",
    "B": "31.21000000",
    "a": "25.36520000",
    "A": "40.66000000",
}


def _make_source_with_collector() -> tuple[BinanceOrderbookSource, list[MarketTick]]:
    bus: Bus[MarketTick] = Bus("market-test")
    received: list[MarketTick] = []

    async def collector(tick: MarketTick) -> None:
        received.append(tick)

    bus.subscribe(collector)
    return BinanceOrderbookSource(market_bus=bus), received


async def test_handle_publishes_orderbook_tick() -> None:
    source, received = _make_source_with_collector()
    before_ms = time.time_ns() // 1_000_000

    await source._handle(json.dumps(SAMPLE_PAYLOAD))

    after_ms = time.time_ns() // 1_000_000
    assert len(received) == 1

    tick = received[0]
    assert isinstance(tick, OrderBookTick)
    assert tick.bid_price == Decimal("25.35190000")
    assert tick.ask_price == Decimal("25.36520000")
    assert tick.bid_quantity == Decimal("31.21000000")
    assert tick.ask_quantity == Decimal("40.66000000")
    assert tick.send_time == 1568014460893
    assert before_ms <= tick.receive_time <= after_ms


async def test_handle_preserves_decimal_precision() -> None:
    """String prices are converted directly to Decimal without float rounding."""
    source, received = _make_source_with_collector()

    payload = dict(SAMPLE_PAYLOAD)
    payload["b"] = "0.00000001"
    payload["a"] = "99999999.99999999"

    await source._handle(json.dumps(payload))

    assert received[0].bid_price == Decimal("0.00000001")
    assert received[0].ask_price == Decimal("99999999.99999999")


async def test_url_uses_lowercase_symbol(monkeypatch) -> None:
    """Binance stream paths require lowercase symbols."""
    monkeypatch.setattr(
        "cex_dex_arbitrage.sources.binance_orderbook.settings",
        type("S", (), {"binance_futures_symbol": "BNBUSDT"})(),
    )
    bus: Bus[MarketTick] = Bus("market-test")
    source = BinanceOrderbookSource(market_bus=bus)
    assert source.url == "wss://fstream.binance.com/ws/bnbusdt@bookTicker"
