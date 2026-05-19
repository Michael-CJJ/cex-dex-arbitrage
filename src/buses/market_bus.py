from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import MarketTick

market_bus: Bus[MarketTick] = Bus("market")
