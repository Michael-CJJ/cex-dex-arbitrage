import json
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import BNBPrice, MarketTick
from cex_dex_arbitrage.utils.ws_client import WSClient

WS_BASE = "wss://stream.binance.com:9443/ws"


class BinanceBNBPriceSource:
    """Publish Binance Spot BNB/USDT mid prices to market_bus."""

    def __init__(self, market_bus: Bus[MarketTick]) -> None:
        self.market_bus = market_bus

    @property
    def url(self) -> str:
        return f"{WS_BASE}/bnbusdt@bookTicker"

    async def run(self) -> None:
        client = WSClient(url=self.url, on_message=self._handle, name="binance_bnb")
        await client.run()

    async def _handle(self, raw: str) -> None:
        msg = json.loads(raw)
        bid = Decimal(msg["b"])
        ask = Decimal(msg["a"])
        if bid <= 0 or ask <= 0:
            return
        await self.market_bus.publish(BNBPrice(mid_price=(bid + ask) / Decimal("2")))
