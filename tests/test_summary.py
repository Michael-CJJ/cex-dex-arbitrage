import asyncio
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.summary import Summary, _readable_ms
from cex_dex_arbitrage.models.final import FinalTradeSummary
from cex_dex_arbitrage.models.result import CexFill, CexWrong, DexFill, TradeResult
from cex_dex_arbitrage.models.signal import Direction
from cex_dex_arbitrage.models.trade import CexTrade, DexTrade, TradeDecision


def _decision(activate_time: int = 1) -> TradeDecision:
    return TradeDecision(
        bps=Decimal("20"),
        direction=Direction.C_TO_D,
        activate_time=activate_time,
        decision_generated_time=activate_time + 1,
        cextrade=CexTrade(
            direction="buy",
            quantity=Decimal("10"),
            expected_price=Decimal("100"),
            acceptable_price=Decimal("100.1"),
        ),
        dextrade=DexTrade(
            direction="sell",
            quantity=Decimal("10"),
            expected_price=Decimal("101"),
            acceptable_price=Decimal("100.9"),
        ),
    )


def _cex_fill(order_id: int = 1, price: Decimal = Decimal("100.1")) -> CexFill:
    return CexFill(
        symbol="BUSDT",
        order_id=order_id,
        client_order_id=f"client-{order_id}",
        status="FILLED",
        direction="buy",
        price=price,
        quantity=Decimal("10"),
        quote_quantity=price * Decimal("10"),
        send_time=10,
        receive_time=11,
    )


def _cex_wrong(order_id: int = 1) -> CexWrong:
    return CexWrong(
        symbol="BUSDT",
        order_id=order_id,
        client_order_id=f"client-{order_id}",
        status="EXPIRED",
        direction="buy",
        price=Decimal("100.1"),
        quantity=Decimal("10"),
        executed_quantity=Decimal("0"),
        quote_quantity=Decimal("0"),
        reason="order expired without fill",
        raw={"status": 200},
        send_time=10,
        receive_time=11,
    )


def _dex_fill(txhash: str = "0xtx", price: Decimal = Decimal("100.9")) -> DexFill:
    return DexFill(
        price=price,
        quantity=Decimal("10"),
        txhash=txhash,
        gas=100_000,
        gas_price_wei=1_000_000_000,
        gas_bnb=Decimal("0.0001"),
        gas_usd=Decimal("0.06"),
        send_time=12,
        receive_time=13,
    )


async def test_summary_publishes_after_both_legs() -> None:
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    result_bus: Bus[TradeResult] = Bus("result-test")
    final_bus: Bus[FinalTradeSummary] = Bus("final-test")
    summaries: list[FinalTradeSummary] = []

    async def collect(summary: FinalTradeSummary) -> None:
        summaries.append(summary)

    final_bus.subscribe(collect)
    Summary(trade_bus=trade_bus, result_bus=result_bus, final_bus=final_bus).start()

    decision = _decision()
    cex = _cex_fill()
    dex = _dex_fill()

    await trade_bus.publish(decision)
    await result_bus.publish(cex)

    assert summaries == []

    await result_bus.publish(dex)

    assert len(summaries) == 1
    summary = summaries[0]
    assert summary == FinalTradeSummary(
        signal_activate_time=_readable_ms(decision.activate_time),
        bps=decision.bps,
        direction="c-d",
        quantity=Decimal("10"),
        cex_expected_price=Decimal("100.0000"),
        cex_price=Decimal("100.1000"),
        cex_fee=Decimal("0.5005"),
        cex_receive_time=_readable_ms(cex.receive_time),
        dex_expected_price=Decimal("101.0000"),
        dex_price=Decimal("100.9000"),
        dex_gas_usd=Decimal("0.0600"),
        dex_receive_time=_readable_ms(dex.receive_time),
        realized_bps=(Decimal("100.9") - Decimal("100.1")) / Decimal("100.1") * Decimal("10000"),
        total_fee=Decimal("0.5605"),
    )


async def test_summary_pairs_results_with_oldest_incomplete_trade() -> None:
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    result_bus: Bus[TradeResult] = Bus("result-test")
    final_bus: Bus[FinalTradeSummary] = Bus("final-test")
    summaries: list[FinalTradeSummary] = []

    async def collect(summary: FinalTradeSummary) -> None:
        summaries.append(summary)

    final_bus.subscribe(collect)
    Summary(trade_bus=trade_bus, result_bus=result_bus, final_bus=final_bus).start()

    first = _decision(activate_time=1)
    second = _decision(activate_time=2)
    first_dex = _dex_fill("0xfirst", Decimal("100.9"))
    second_dex = _dex_fill("0xsecond", Decimal("200.9"))
    first_cex = _cex_fill(1, Decimal("100.1"))
    second_cex = _cex_fill(2, Decimal("200.1"))

    await trade_bus.publish(first)
    await trade_bus.publish(second)
    await result_bus.publish(first_dex)
    await result_bus.publish(first_cex)
    await result_bus.publish(second_cex)
    await result_bus.publish(second_dex)

    assert [(summary.signal_activate_time, summary.cex_price, summary.dex_price) for summary in summaries] == [
        (_readable_ms(first.activate_time), Decimal("100.1000"), Decimal("100.9000")),
        (_readable_ms(second.activate_time), Decimal("200.1000"), Decimal("200.9000")),
    ]


async def test_summary_treats_cex_wrong_as_completed_cex_leg() -> None:
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    result_bus: Bus[TradeResult] = Bus("result-test")
    final_bus: Bus[FinalTradeSummary] = Bus("final-test")
    summaries: list[FinalTradeSummary] = []

    async def collect(summary: FinalTradeSummary) -> None:
        summaries.append(summary)

    final_bus.subscribe(collect)
    Summary(trade_bus=trade_bus, result_bus=result_bus, final_bus=final_bus).start()

    cex_wrong = _cex_wrong()

    await trade_bus.publish(_decision())
    await result_bus.publish(cex_wrong)
    dex = _dex_fill()
    await result_bus.publish(dex)

    assert len(summaries) == 1
    assert summaries[0].cex_price is None
    assert summaries[0].cex_fee == Decimal("0.0000")
    assert summaries[0].cex_receive_time == _readable_ms(cex_wrong.receive_time)
    assert summaries[0].dex_gas_usd == Decimal("0.0600")
    assert summaries[0].realized_bps is None
    assert summaries[0].total_fee == Decimal("0.0600")


async def test_summary_wait_idle_waits_for_pending_and_final_bus() -> None:
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    result_bus: Bus[TradeResult] = Bus("result-test")
    final_bus: Bus[FinalTradeSummary] = Bus("final-test")
    final_started = asyncio.Event()
    final_finish = asyncio.Event()

    async def slow_final_handler(summary: FinalTradeSummary) -> None:
        final_started.set()
        await final_finish.wait()

    final_bus.subscribe(slow_final_handler)
    summary = Summary(trade_bus=trade_bus, result_bus=result_bus, final_bus=final_bus)
    summary.start()

    await trade_bus.publish(_decision())
    idle_task = asyncio.create_task(summary.wait_idle())
    await asyncio.sleep(0)

    assert summary.pending_count == 1
    assert not idle_task.done()

    await result_bus.publish(_cex_fill())
    assert summary.pending_count == 1
    assert not idle_task.done()

    dex_publish_task = asyncio.create_task(result_bus.publish(_dex_fill()))
    await asyncio.wait_for(final_started.wait(), timeout=1)
    await asyncio.sleep(0)

    assert summary.pending_count == 0
    assert summary.finalizing_count == 1
    assert not idle_task.done()

    final_finish.set()
    await dex_publish_task
    await idle_task

    assert summary.finalizing_count == 0
