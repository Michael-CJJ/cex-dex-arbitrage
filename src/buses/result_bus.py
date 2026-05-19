from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.result import TradeResult

result_bus: Bus[TradeResult] = Bus("result")
