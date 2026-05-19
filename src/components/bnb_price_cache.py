from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import BNBPrice, MarketTick


WEI_PER_BNB = Decimal(10**18)


class BNBPriceCache:
    def __init__(self, market_bus: Bus[MarketTick]) -> None:
        self.market_bus = market_bus
        self.mid_price: Decimal | None = None

    def start(self) -> None:
        self.market_bus.subscribe(self._on_tick)

    async def _on_tick(self, tick: MarketTick) -> None:
        if isinstance(tick, BNBPrice) and tick.mid_price > 0:
            self.mid_price = tick.mid_price

    def gas_bnb(self, gas_used: int, gas_price_wei: int) -> Decimal:
        return Decimal(gas_used) * Decimal(gas_price_wei) / WEI_PER_BNB

    def gas_usd(self, gas_used: int, gas_price_wei: int) -> Decimal | None:
        if self.mid_price is None:
            return None
        return self.gas_bnb(gas_used, gas_price_wei) * self.mid_price
