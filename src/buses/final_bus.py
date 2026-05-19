from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.final import FinalTradeSummary

final_bus: Bus[FinalTradeSummary] = Bus("final")
