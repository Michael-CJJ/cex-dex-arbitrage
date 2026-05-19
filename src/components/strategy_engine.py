import time
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR

from cex_dex_arbitrage.config import settings
from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.signal import ArbSignal, Direction
from cex_dex_arbitrage.models.trade import CexTrade, DexTrade, TradeDecision
BPS = Decimal("10000")


class StrategyEngine:
    """Turn arbitrage signals into bounded trade decisions."""

    def __init__(
        self,
        signal_bus: Bus[ArbSignal],
        trade_bus: Bus[TradeDecision],
    ) -> None:
        self.signal_bus = signal_bus
        self.trade_bus = trade_bus
        self._dex_token0_positions = settings.initial_d_to_c_positions
        self._last_trade_direction: Direction | None = None
        self._last_trade_activate_time: int | None = None
        self._running = True

    def start(self) -> None:
        self._running = True
        self.signal_bus.subscribe(self._on_signal)

    def stop(self) -> None:
        self._running = False

    async def _on_signal(self, signal: ArbSignal) -> None:
        if not self._running:
            return

        if self._is_same_direction_cooling_down(signal):
            return

        action = self._position_action(signal.direction)
        if action is None:
            return

        decision = self._build_decision(signal)
        if decision is None:
            return

        if not self._running:
            return

        self._apply_position_action(action)
        self._last_trade_direction = signal.direction
        self._last_trade_activate_time = signal.activate_time
        await self.trade_bus.publish(decision)

    def _build_decision(self, signal: ArbSignal) -> TradeDecision | None:

        quantity = settings.quantity
        quantity = self._cex_quantity(quantity)
        if quantity <= 0:
            return None

        if signal.direction == Direction.C_TO_D:
            cex_direction = "buy"
            dex_direction = "sell"
            cex_price = signal.tick1.ask_price
            dex_price = signal.tick2.price
        else:
            cex_direction = "sell"
            dex_direction = "buy"
            cex_price = signal.tick1.bid_price
            dex_price = signal.tick2.price

        return TradeDecision(
            bps=signal.bps,
            direction=signal.direction,
            activate_time=signal.activate_time,
            decision_generated_time=time.time_ns() // 1_000_000,
            cextrade=CexTrade(
                direction=cex_direction,
                quantity=quantity,
                expected_price=cex_price,
                acceptable_price=self._cex_acceptable_price(cex_direction, cex_price),
            ),
            dextrade=DexTrade(
                direction=dex_direction,
                quantity=quantity,
                expected_price=dex_price,
                acceptable_price=self._acceptable_price(dex_direction, dex_price),
            ),
        )

    def _acceptable_price(self, direction: str, expected_price: Decimal) -> Decimal:
        tolerance_bps = self._acceptable_price_tolerance_bps()
        price_delta = tolerance_bps / BPS
        if direction == "buy":
            return expected_price * (Decimal("1") + price_delta)
        return expected_price * (Decimal("1") - price_delta)

    def _cex_quantity(self, quantity: Decimal) -> Decimal:
        return Decimal(str(quantity)).quantize(
            _precision_unit(settings.cex_quantity_precision),
            rounding=ROUND_FLOOR,
        )

    def _cex_acceptable_price(self, direction: str, expected_price: Decimal) -> Decimal:
        acceptable_price = self._acceptable_price(direction, expected_price)
        rounding = ROUND_FLOOR if direction == "buy" else ROUND_CEILING
        return acceptable_price.quantize(
            _precision_unit(settings.cex_price_precision),
            rounding=rounding,
        )

    def _acceptable_price_tolerance_bps(self) -> Decimal:
        base_bps = Decimal(str(settings.base_bps))
        threshold_bps = Decimal(str(settings.threshold_bps))
        return abs((base_bps + threshold_bps / Decimal("2")) - base_bps)

    def _is_same_direction_cooling_down(self, signal: ArbSignal) -> bool:
        return (
            self._last_trade_direction == signal.direction
            and self._last_trade_activate_time is not None
            and abs(signal.activate_time - self._last_trade_activate_time) < settings.min_signal_interval_ms
        )

    def _position_action(self, direction: Direction) -> str | None:
        dex_direction = _dex_direction(direction)
        if dex_direction == "sell":
            if self._dex_token0_positions <= 0:
                return None
            return "consume"

        if self._dex_token0_positions >= settings.max_positions:
            return None
        return "restore"

    def _apply_position_action(self, action: str) -> None:
        if action == "consume":
            self._dex_token0_positions -= 1
            return
        self._dex_token0_positions += 1


def _dex_direction(direction: Direction) -> str:
    if direction == Direction.C_TO_D:
        return "sell"
    return "buy"


def _precision_unit(precision: int) -> Decimal:
    if precision < 0:
        raise ValueError(f"precision must be non-negative: {precision}")
    return Decimal("1").scaleb(-precision)
