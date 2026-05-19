import asyncio
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.arb_calculator import ArbCalculator
from cex_dex_arbitrage.components.strategy_engine import StrategyEngine
from cex_dex_arbitrage.models.market import MarketTick, OrderBookTick, SwapTick
from cex_dex_arbitrage.models.signal import ArbSignal
from cex_dex_arbitrage.models.trade import TradeDecision


async def main() -> None:
    market_bus: Bus[MarketTick] = Bus("market-demo")
    signal_bus: Bus[ArbSignal] = Bus("signal-demo")
    trade_bus: Bus[TradeDecision] = Bus("trade-demo")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    arb = ArbCalculator(market_bus=market_bus, signal_bus=signal_bus)
    strategy = StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus)
    arb.start()
    strategy.start()

    now_ms = time.time_ns() // 1_000_000
    await market_bus.publish(
        OrderBookTick(
            bid_price=Decimal("99.95"),
            ask_price=Decimal("100.05"),
            bid_quantity=Decimal("100"),
            ask_quantity=Decimal("100"),
            send_time=now_ms,
            receive_time=now_ms,
        )
    )
    await market_bus.publish(
        SwapTick(
            direction="1->0",
            quantity=Decimal("100"),
            price=Decimal("99.40"),
            send_time=now_ms + 1,
            receive_time=now_ms + 1,
        )
    )

    if not decisions:
        print("No decision generated.")
        return

    decision = decisions[-1]
    print(
        "decision",
        {
            "direction": decision.direction.value,
            "bps": str(decision.bps.quantize(Decimal("0.0001"))),
            "cex": decision.cextrade.direction,
            "dex": decision.dextrade.direction,
            "quantity": str(decision.cextrade.quantity),
        },
    )


if __name__ == "__main__":
    asyncio.run(main())
