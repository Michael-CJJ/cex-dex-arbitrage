import asyncio
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.trader import Trader
from cex_dex_arbitrage.models.market import OrderBookTick, SwapTick
from cex_dex_arbitrage.models.signal import ArbSignal, Direction
from cex_dex_arbitrage.models.trade import CexTrade, DexTrade, TradeDecision


def _decision() -> TradeDecision:
    ob = OrderBookTick(
        bid_price=Decimal("99"),
        ask_price=Decimal("101"),
        bid_quantity=Decimal("3"),
        ask_quantity=Decimal("2"),
        send_time=1,
        receive_time=1,
    )
    swap = SwapTick(
        direction="0->1",
        quantity=Decimal("5"),
        price=Decimal("102"),
        send_time=2,
        receive_time=2,
    )
    signal = ArbSignal(
        bps=Decimal("200"),
        direction=Direction.C_TO_D,
        activate_time=2,
        tick1=ob,
        tick2=swap,
    )
    return TradeDecision(
        bps=signal.bps,
        direction=signal.direction,
        activate_time=signal.activate_time,
        decision_generated_time=3,
        cextrade=CexTrade(
            direction="buy",
            quantity=Decimal("2"),
            expected_price=Decimal("101"),
            acceptable_price=Decimal("101"),
        ),
        dextrade=DexTrade(
            direction="sell",
            quantity=Decimal("2"),
            expected_price=Decimal("102"),
            acceptable_price=Decimal("102"),
        ),
    )


async def test_trader_dispatches_trade_decision_to_both_legs(monkeypatch) -> None:
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    received: list[tuple[str, TradeDecision]] = []

    async def fake_cex_trade(decision: TradeDecision) -> None:
        received.append(("cex", decision))

    async def fake_dex_trade(decision: TradeDecision) -> None:
        received.append(("dex", decision))

    monkeypatch.setattr("cex_dex_arbitrage.components.trader.cex_trade", fake_cex_trade)
    monkeypatch.setattr("cex_dex_arbitrage.components.trader.dex_trade", fake_dex_trade)
    monkeypatch.setattr("cex_dex_arbitrage.components.trader.initialize_dex_trade", lambda: None)
    monkeypatch.setattr("cex_dex_arbitrage.components.trader.initialize_dex_nonce", lambda: None)
    Trader(trade_bus=trade_bus).start()

    decision = _decision()
    await trade_bus.publish(decision)

    assert sorted(received, key=lambda item: item[0]) == [
        ("cex", decision),
        ("dex", decision),
    ]


async def test_trader_wait_idle_waits_for_active_trade(monkeypatch) -> None:
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    started: list[str] = []
    both_started = asyncio.Event()
    finish = asyncio.Event()

    async def fake_cex_trade(decision: TradeDecision) -> None:
        started.append("cex")
        if len(started) == 2:
            both_started.set()
        await finish.wait()

    async def fake_dex_trade(decision: TradeDecision) -> None:
        started.append("dex")
        if len(started) == 2:
            both_started.set()
        await finish.wait()

    monkeypatch.setattr("cex_dex_arbitrage.components.trader.cex_trade", fake_cex_trade)
    monkeypatch.setattr("cex_dex_arbitrage.components.trader.dex_trade", fake_dex_trade)
    monkeypatch.setattr("cex_dex_arbitrage.components.trader.initialize_dex_trade", lambda: None)
    monkeypatch.setattr("cex_dex_arbitrage.components.trader.initialize_dex_nonce", lambda: None)
    trader = Trader(trade_bus=trade_bus)
    trader.start()

    publish_task = asyncio.create_task(trade_bus.publish(_decision()))
    await asyncio.wait_for(both_started.wait(), timeout=1)

    idle_task = asyncio.create_task(trader.wait_idle())
    await asyncio.sleep(0)

    assert trader.active_trades == 1
    assert not idle_task.done()

    finish.set()
    await publish_task
    await idle_task

    assert trader.active_trades == 0


def test_trader_initializes_dex_trade_and_nonce(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr("cex_dex_arbitrage.components.trader.initialize_dex_trade", lambda: calls.append("trade"))
    monkeypatch.setattr("cex_dex_arbitrage.components.trader.initialize_dex_nonce", lambda: calls.append("nonce"))

    Trader(trade_bus=Bus("trade-test"))

    assert calls == ["trade", "nonce"]
