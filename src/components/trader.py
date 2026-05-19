import asyncio

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.trade import TradeDecision
from cex_dex_arbitrage.trading.cex_trade import cex_trade
from cex_dex_arbitrage.trading.dex_trade import dex_trade, initialize_dex_nonce, initialize_dex_trade


class Trader:
    """Dispatch CEX and DEX execution tasks for each trade decision."""

    def __init__(self, trade_bus: Bus[TradeDecision]) -> None:
        self.trade_bus = trade_bus
        self._active_trades = 0
        self._idle = asyncio.Event()
        self._idle.set()
        initialize_dex_trade()
        initialize_dex_nonce()

    def start(self) -> None:
        self.trade_bus.subscribe(self._on_decision)

    async def _on_decision(self, decision: TradeDecision) -> None:
        self._active_trades += 1
        self._idle.clear()
        try:
            await asyncio.gather(
                cex_trade(decision),
                dex_trade(decision),
            )
        finally:
            self._active_trades -= 1
            if self._active_trades == 0:
                self._idle.set()

    async def wait_idle(self) -> None:
        await self._idle.wait()

    @property
    def active_trades(self) -> int:
        return self._active_trades
