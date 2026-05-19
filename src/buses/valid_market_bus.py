from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import MarketTick

valid_market_bus: Bus[MarketTick] = Bus("valid_market")
