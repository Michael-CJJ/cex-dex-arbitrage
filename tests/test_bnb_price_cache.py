from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.bnb_price_cache import BNBPriceCache
from cex_dex_arbitrage.models.market import BNBPrice, MarketTick


async def test_bnb_price_cache_converts_gas_to_usd() -> None:
    market_bus: Bus[MarketTick] = Bus("bnb-cache-test")
    cache = BNBPriceCache(market_bus=market_bus)
    cache.start()

    assert cache.gas_usd(134475, 100000000) is None

    await market_bus.publish(BNBPrice(mid_price=Decimal("600")))

    assert cache.gas_bnb(134475, 100000000) == Decimal("0.0000134475")
    assert cache.gas_usd(134475, 100000000) == Decimal("0.0080685000")
