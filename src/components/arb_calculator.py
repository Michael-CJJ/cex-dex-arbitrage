from decimal import Decimal, InvalidOperation

from cex_dex_arbitrage.config import settings
from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import BNBPrice, MarketTick, OrderBookTick, SwapTick
from cex_dex_arbitrage.models.signal import ArbSignal, Direction

BPS = Decimal("10000")


class ArbCalculator:
    """Maintain latest CEX/DEX state and publish signals when spreads cross threshold."""

    def __init__(self, market_bus: Bus[MarketTick], signal_bus: Bus[ArbSignal]) -> None:
        self.market_bus = market_bus
        self.signal_bus = signal_bus
        self._latest_ob: OrderBookTick | None = None
        self._latest_swap: SwapTick | None = None
        self._latest_bnb_price: BNBPrice | None = None
        self._running = True

    def start(self) -> None:
        self._running = True
        self.market_bus.subscribe(self._on_tick)

    def stop(self) -> None:
        self._running = False

    async def _on_tick(self, tick: MarketTick) -> None:
        if not self._running:
            return

        if isinstance(tick, OrderBookTick):
            self._latest_ob = tick
        elif isinstance(tick, SwapTick):
            self._latest_swap = tick
        elif isinstance(tick, BNBPrice):
            self._latest_bnb_price = tick
            if not settings.pool_bnb:
                return

        if self._latest_ob is None or self._latest_swap is None:
            return

        signal = self._build_signal(self._latest_ob, self._latest_swap)
        if signal is None:
            return

        if not self._running:
            return

        await self.signal_bus.publish(signal)

    def _build_signal(self, ob: OrderBookTick, swap: SwapTick) -> ArbSignal | None:
        spread_bps = self._dex_minus_cex_bps(ob, swap)
        if spread_bps is None:
            return None

        base_bps = Decimal(str(settings.base_bps))
        threshold_bps = abs(Decimal(str(settings.threshold_bps)))
        deviation_bps = spread_bps - base_bps

        if deviation_bps > threshold_bps:
            direction = Direction.C_TO_D
            cex_quantity = ob.ask_quantity
        elif deviation_bps < -threshold_bps:
            direction = Direction.D_TO_C
            cex_quantity = ob.bid_quantity
        else:
            return None

        if not self._has_positive_liquidity(cex_quantity, swap.quantity):
            return None
        return ArbSignal(
            bps=spread_bps,
            direction=direction,
            activate_time=max(ob.send_time, swap.send_time),
            tick1=ob,
            tick2=swap,
        )

    def _dex_minus_cex_bps(self, ob: OrderBookTick, swap: SwapTick) -> Decimal | None:
        try:
            cex_mid = (ob.bid_price + ob.ask_price) / Decimal("2")
            if cex_mid <= 0:
                return None
            dex_price = self._dex_price_for_cex_quote(swap)
            if dex_price is None:
                return None
            return (dex_price - cex_mid) / cex_mid * BPS
        except (InvalidOperation, ZeroDivisionError):
            return None

    def _dex_price_for_cex_quote(self, swap: SwapTick) -> Decimal | None:
        if not settings.pool_bnb:
            return swap.price
        if self._latest_bnb_price is None:
            return None
        if self._latest_bnb_price.mid_price <= 0:
            return None
        return swap.price * self._latest_bnb_price.mid_price

    def _has_positive_liquidity(self, cex_quantity: Decimal, dex_quantity: Decimal) -> bool:
        return cex_quantity > 0 and dex_quantity > 0
