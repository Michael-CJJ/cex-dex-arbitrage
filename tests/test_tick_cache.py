import asyncio
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.tick_cache import DEFAULT_SWAP_QUIET_MS, TickCache
from cex_dex_arbitrage.models.market import BNBPrice, MarketTick, OrderBookTick, SwapTick


def _ob() -> OrderBookTick:
    return OrderBookTick(
        bid_price=Decimal("99"),
        ask_price=Decimal("101"),
        bid_quantity=Decimal("3"),
        ask_quantity=Decimal("2"),
        send_time=1,
        receive_time=1,
    )


def _swap(price: str, send_time: int) -> SwapTick:
    return SwapTick(
        direction="0->1",
        quantity=Decimal("5"),
        price=Decimal(price),
        send_time=send_time,
        receive_time=send_time,
    )


def _make_cache(
    *,
    swap_quiet_ms: int = DEFAULT_SWAP_QUIET_MS,
) -> tuple[Bus[MarketTick], list[MarketTick], TickCache]:
    market_bus: Bus[MarketTick] = Bus("raw-market-test")
    valid_market_bus: Bus[MarketTick] = Bus("valid-market-test")
    valid_ticks: list[MarketTick] = []

    async def collect(tick: MarketTick) -> None:
        valid_ticks.append(tick)

    valid_market_bus.subscribe(collect)
    cache = TickCache(
        market_bus=market_bus,
        valid_market_bus=valid_market_bus,
        swap_quiet_ms=swap_quiet_ms,
    )
    cache.start()
    return market_bus, valid_ticks, cache


async def test_orderbook_ticks_pass_through_immediately() -> None:
    market_bus, valid_ticks, _ = _make_cache()
    tick = _ob()

    await market_bus.publish(tick)

    assert valid_ticks == [tick]


async def test_bnb_price_ticks_pass_through_immediately() -> None:
    market_bus, valid_ticks, _ = _make_cache()
    tick = BNBPrice(mid_price=Decimal("600"))

    await market_bus.publish(tick)

    assert valid_ticks == [tick]


async def test_swap_ticks_publish_only_last_tick_after_quiet_period() -> None:
    market_bus, valid_ticks, _ = _make_cache()
    first = _swap("101", 1)
    second = _swap("102", 2)
    third = _swap("103", 3)

    await market_bus.publish(first)
    await market_bus.publish(second)
    await market_bus.publish(third)

    assert valid_ticks == []

    await asyncio.sleep((DEFAULT_SWAP_QUIET_MS + 5) / 1000)

    assert valid_ticks == [third]


async def test_stop_drops_pending_swap_tick() -> None:
    market_bus, valid_ticks, cache = _make_cache(swap_quiet_ms=10)

    await market_bus.publish(_swap("101", 1))
    cache.stop()
    await asyncio.sleep(0.02)

    assert valid_ticks == []
