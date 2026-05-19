from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class FinalTradeSummary:
    signal_activate_time: str
    bps: Decimal
    direction: str
    quantity: Decimal
    cex_expected_price: Decimal
    cex_price: Decimal | None
    cex_fee: Decimal
    cex_receive_time: str
    dex_expected_price: Decimal
    dex_price: Decimal
    dex_gas_usd: Decimal | None
    dex_receive_time: str
    realized_bps: Decimal | None
    total_fee: Decimal | None
