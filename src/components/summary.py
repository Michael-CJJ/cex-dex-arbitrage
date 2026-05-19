import asyncio
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.result import CexFill, CexWrong, DexFill, TradeResult
from cex_dex_arbitrage.models.final import FinalTradeSummary
from cex_dex_arbitrage.models.trade import TradeDecision
from cex_dex_arbitrage.utils.logger import get_logger

log = get_logger(__name__)

BPS = Decimal("10000")
CEX_FEE_RATE = Decimal("0.0005")
FOUR_PLACES = Decimal("0.0001")
CexResult = CexFill | CexWrong


@dataclass
class _PendingTrade:
    decision: TradeDecision
    cex_result: CexResult | None = None
    dex_result: DexFill | None = None


class Summary:
    """Subscribe to trade/result buses and publish completed two-leg summaries."""

    def __init__(
        self,
        trade_bus: Bus[TradeDecision],
        result_bus: Bus[TradeResult],
        final_bus: Bus[FinalTradeSummary],
    ) -> None:
        self.trade_bus = trade_bus
        self.result_bus = result_bus
        self.final_bus = final_bus
        self._pending: list[_PendingTrade] = []
        self._finalizing = 0
        self._lock = asyncio.Lock()
        self._idle = asyncio.Event()
        self._idle.set()

    def start(self) -> None:
        self.trade_bus.subscribe(self._on_trade)
        self.result_bus.subscribe(self._on_result)

    async def _on_trade(self, decision: TradeDecision) -> None:
        async with self._lock:
            self._pending.append(_PendingTrade(decision=decision))
            self._refresh_idle()

    async def _on_result(self, result: TradeResult) -> None:
        summary: FinalTradeSummary | None = None
        async with self._lock:
            pending = self._match_pending_trade(result)
            if pending is None:
                log.warning("trade result received without pending decision")
                return

            if isinstance(result, (CexFill, CexWrong)):
                pending.cex_result = result
            elif isinstance(result, DexFill):
                pending.dex_result = result

            if pending.cex_result is not None and pending.dex_result is not None:
                summary = _build_final_summary(pending)
                self._pending.remove(pending)
                self._finalizing += 1
                self._refresh_idle()

        if summary is not None:
            try:
                await self.final_bus.publish(summary)
            finally:
                async with self._lock:
                    self._finalizing -= 1
                    self._refresh_idle()

    async def wait_idle(self) -> None:
        await self._idle.wait()

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def finalizing_count(self) -> int:
        return self._finalizing

    def _match_pending_trade(self, result: TradeResult) -> _PendingTrade | None:
        if isinstance(result, (CexFill, CexWrong)):
            return next((trade for trade in self._pending if trade.cex_result is None), None)
        if isinstance(result, DexFill):
            return next((trade for trade in self._pending if trade.dex_result is None), None)
        return None

    def _refresh_idle(self) -> None:
        if not self._pending and self._finalizing == 0:
            self._idle.set()
            return
        self._idle.clear()


def _build_final_summary(pending: _PendingTrade) -> FinalTradeSummary:
    if pending.cex_result is None or pending.dex_result is None:
        raise ValueError("pending trade is not complete")

    decision = pending.decision
    cex_result = pending.cex_result
    dex_result = pending.dex_result
    cex_price = _cex_price(cex_result)
    cex_fee = _cex_fee(cex_result)
    dex_gas = _q4_or_none(dex_result.gas_usd)

    return FinalTradeSummary(
        signal_activate_time=_readable_ms(decision.activate_time),
        bps=decision.bps,
        direction=decision.direction.value,
        quantity=decision.cextrade.quantity,
        cex_expected_price=_q4(decision.cextrade.expected_price),
        cex_price=_q4_or_none(cex_price),
        cex_fee=cex_fee,
        cex_receive_time=_readable_ms(cex_result.receive_time),
        dex_expected_price=_q4(decision.dextrade.expected_price),
        dex_price=_q4(dex_result.price),
        dex_gas_usd=dex_gas,
        dex_receive_time=_readable_ms(dex_result.receive_time),
        realized_bps=_real_bps(cex_price, dex_result.price),
        total_fee=_total_fee(cex_fee, dex_gas),
    )


def _q4(value: Decimal) -> Decimal:
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def _q4_or_none(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return _q4(value)


def _readable_ms(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _cex_price(result: CexResult) -> Decimal | None:
    if isinstance(result, CexFill):
        return result.price
    return None


def _cex_fee(result: CexResult) -> Decimal:
    quote_quantity = result.quote_quantity
    if quote_quantity is None or quote_quantity <= 0:
        return Decimal("0.0000")
    return _q4(quote_quantity * CEX_FEE_RATE)


def _real_bps(cex_price: Decimal | None, dex_price: Decimal) -> Decimal | None:
    if cex_price is None or cex_price <= 0:
        return None
    return (dex_price - cex_price) / cex_price * BPS


def _total_fee(cex_fee: Decimal, dex_gas: Decimal | None) -> Decimal | None:
    if dex_gas is None:
        return None
    return _q4(cex_fee + dex_gas)
