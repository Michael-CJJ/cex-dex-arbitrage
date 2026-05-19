import json
import time
from decimal import Decimal

from cex_dex_arbitrage.config import settings
from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import MarketTick, OrderBookTick
from cex_dex_arbitrage.utils.ws_client import WSClient

WS_BASE = "wss://fstream.binance.com/ws"


class BinanceOrderbookSource:
    """Publish Binance Futures best bid/ask ticks to market_bus.

    bookTicker payload:
        {"e":"bookTicker","u":...,"E":<event_ms>,"T":<txn_ms>,"s":"BNBUSDT",
         "b":"<bid_px>","B":"<bid_qty>","a":"<ask_px>","A":"<ask_qty>"}
    """

    def __init__(self, market_bus: Bus[MarketTick]) -> None:
        self.market_bus = market_bus

    @property
    def url(self) -> str:
        return f"{WS_BASE}/{settings.binance_futures_symbol.lower()}@bookTicker"

    async def run(self) -> None:
        client = WSClient(url=self.url, on_message=self._handle, name="binance_ob")
        await client.run()

    async def _handle(self, raw: str) -> None:
        msg = json.loads(raw)
        tick = OrderBookTick(
            bid_price=Decimal(msg["b"]),
            ask_price=Decimal(msg["a"]),
            bid_quantity=Decimal(msg["B"]),
            ask_quantity=Decimal(msg["A"]),
            send_time=int(msg["E"]),
            receive_time=time.time_ns() // 1_000_000,
        )
        await self.market_bus.publish(tick)
