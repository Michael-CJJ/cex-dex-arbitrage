from dataclasses import dataclass
from decimal import Decimal

from cex_dex_arbitrage.models.signal import Direction


@dataclass(frozen=True)
class CexTrade:
    direction: str
    quantity: Decimal
    expected_price: Decimal
    acceptable_price: Decimal


@dataclass(frozen=True)
class DexTrade:
    direction: str
    quantity: Decimal
    expected_price: Decimal
    acceptable_price: Decimal


@dataclass(frozen=True)
class TradeDecision:
    bps: Decimal
    direction: Direction
    activate_time: int
    decision_generated_time: int
    cextrade: CexTrade
    dextrade: DexTrade
