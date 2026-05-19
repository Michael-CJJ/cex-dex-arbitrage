from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.trade import TradeDecision

trade_bus: Bus[TradeDecision] = Bus("trade")
