import json
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import BNBPrice, MarketTick
from cex_dex_arbitrage.sources.binance_bnb_price import BinanceBNBPriceSource


SAMPLE_PAYLOAD = {
    "u": 400900217,
    "s": "BNBUSDT",
    "b": "601.20000000",
    "B": "10.00000000",
    "a": "601.40000000",
    "A": "11.00000000",
}


def _make_source_with_collector() -> tuple[BinanceBNBPriceSource, list[MarketTick]]:
    bus: Bus[MarketTick] = Bus("market-test")
    received: list[MarketTick] = []

    async def collector(tick: MarketTick) -> None:
        received.append(tick)

    bus.subscribe(collector)
    return BinanceBNBPriceSource(market_bus=bus), received


async def test_handle_publishes_bnb_mid_price() -> None:
    source, received = _make_source_with_collector()

    await source._handle(json.dumps(SAMPLE_PAYLOAD))

    assert received == [BNBPrice(mid_price=Decimal("601.30000000"))]


async def test_handle_ignores_non_positive_price() -> None:
    source, received = _make_source_with_collector()
    payload = dict(SAMPLE_PAYLOAD)
    payload["b"] = "0"

    await source._handle(json.dumps(payload))

    assert received == []


async def test_url_uses_spot_bnbusdt_book_ticker() -> None:
    bus: Bus[MarketTick] = Bus("market-test")
    source = BinanceBNBPriceSource(market_bus=bus)
    assert source.url == "wss://stream.binance.com:9443/ws/bnbusdt@bookTicker"
