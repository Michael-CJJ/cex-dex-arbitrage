from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class OrderBookTick:
    """Best bid/ask snapshot from Binance Futures bookTicker."""
    bid_price: Decimal
    ask_price: Decimal
    bid_quantity: Decimal
    ask_quantity: Decimal
    send_time: int       # Exchange event time in ms since epoch.
    receive_time: int    # Local receive time in ms since epoch.


@dataclass(frozen=True)
class SwapTick:
    """Decoded PancakeSwap V3 Swap event state."""
    direction: str       # "0->1" or "1->0" token direction.
    quantity: Decimal
    price: Decimal       # Latest token0-in-token1 pool price after the swap.
    send_time: int       # Chain logs do not carry event time; use receive_time.
    receive_time: int    # Local receive time in ms since epoch.


@dataclass(frozen=True)
class BNBPrice:
    """BNB/USDT mid price from Binance Spot."""
    mid_price: Decimal


MarketTick = OrderBookTick | SwapTick | BNBPrice
