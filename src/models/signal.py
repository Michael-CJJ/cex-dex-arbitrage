from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from cex_dex_arbitrage.models.market import OrderBookTick, SwapTick


class Direction(str, Enum):
    C_TO_D = "c-d"   # Buy on CEX, sell on DEX.
    D_TO_C = "d-c"   # Buy on DEX, sell on CEX.


@dataclass(frozen=True)
class ArbSignal:
    bps: Decimal
    direction: Direction
    activate_time: int
    tick1: OrderBookTick
    tick2: SwapTick
