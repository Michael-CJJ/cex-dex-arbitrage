from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.signal import ArbSignal

signal_bus: Bus[ArbSignal] = Bus("signal")
