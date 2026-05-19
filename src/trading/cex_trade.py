from typing import Any

from cex_dex_arbitrage.config import settings
from cex_dex_arbitrage.models.trade import TradeDecision
from cex_dex_arbitrage.sources.binance_orderfill import place_fok_limit_order


async def cex_trade(decision: TradeDecision) -> dict[str, Any]:
    cex = decision.cextrade
    response = await place_fok_limit_order(
        symbol=settings.binance_futures_symbol,
        side=_binance_side(cex.direction),
        quantity=cex.quantity,
        price=cex.acceptable_price,
    )
    return response


def _binance_side(direction: str) -> str:
    if direction == "buy":
        return "BUY"
    if direction == "sell":
        return "SELL"
    raise ValueError(f"unsupported cex direction: {direction}")
