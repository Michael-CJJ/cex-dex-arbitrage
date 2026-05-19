from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.strategy_engine import StrategyEngine
from cex_dex_arbitrage.models.market import OrderBookTick, SwapTick
from cex_dex_arbitrage.models.signal import ArbSignal, Direction
from cex_dex_arbitrage.models.trade import CexTrade, DexTrade, TradeDecision


def _signal(
    activate_time: int = 2,
    ask_quantity: str = "2",
    direction: Direction = Direction.C_TO_D,
) -> ArbSignal:
    ob = OrderBookTick(
        bid_price=Decimal("99"),
        ask_price=Decimal("101"),
        bid_quantity=Decimal("3"),
        ask_quantity=Decimal(ask_quantity),
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
    return ArbSignal(
        bps=Decimal("200"),
        direction=direction,
        activate_time=activate_time,
        tick1=ob,
        tick2=swap,
    )


def _settings(
    *,
    cex_quantity_precision: int = 0,
    cex_price_precision: int = 4,
    min_signal_interval_ms: int = 30_000,
    max_positions: int = 1,
    initial_d_to_c_positions: int = 0,
    quantity: Decimal = Decimal("2"),
):
    return type(
        "S",
        (),
        {
            "base_bps": -30,
            "threshold_bps": 10,
            "cex_quantity_precision": cex_quantity_precision,
            "cex_price_precision": cex_price_precision,
            "min_signal_interval_ms": min_signal_interval_ms,
            "max_positions": max_positions,
            "initial_d_to_c_positions": initial_d_to_c_positions,
            "quantity": quantity,
        },
    )()


async def test_strategy_engine_publishes_trade_decision(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(quantity=Decimal("10"), initial_d_to_c_positions=1),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    signal = _signal()
    await signal_bus.publish(signal)

    assert decisions == [
        TradeDecision(
            bps=signal.bps,
            direction=signal.direction,
            activate_time=signal.activate_time,
            decision_generated_time=1_700_000_000_123,
            cextrade=CexTrade(
                direction="buy",
                quantity=Decimal("10"),
                expected_price=Decimal("101"),
                acceptable_price=Decimal("101.0505"),
            ),
            dextrade=DexTrade(
                direction="sell",
                quantity=Decimal("10"),
                expected_price=Decimal("102"),
                acceptable_price=Decimal("101.9490"),
            ),
        )
    ]


async def test_strategy_engine_ignores_consecutive_same_direction_within_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(max_positions=3, initial_d_to_c_positions=3),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    first_signal = _signal(activate_time=1_000)
    ignored_signal = _signal(activate_time=30_999)
    next_signal = _signal(activate_time=31_000)

    await signal_bus.publish(first_signal)
    await signal_bus.publish(ignored_signal)
    await signal_bus.publish(next_signal)

    assert decisions == [
        StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus)._build_decision(first_signal),
        StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus)._build_decision(next_signal),
    ]


async def test_strategy_engine_allows_opposite_direction_without_cooldown(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(max_positions=1, initial_d_to_c_positions=1),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    await signal_bus.publish(_signal(activate_time=1_000, direction=Direction.C_TO_D))
    await signal_bus.publish(_signal(activate_time=1_001, direction=Direction.D_TO_C))
    await signal_bus.publish(_signal(activate_time=1_002, direction=Direction.C_TO_D))

    assert [decision.direction for decision in decisions] == [
        Direction.C_TO_D,
        Direction.D_TO_C,
        Direction.C_TO_D,
    ]


async def test_strategy_engine_ignores_c_to_d_without_available_dex_token0(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(initial_d_to_c_positions=0),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    await signal_bus.publish(_signal(activate_time=1_000, direction=Direction.C_TO_D))

    assert decisions == []


async def test_strategy_engine_allows_d_to_c_without_available_dex_token0(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(initial_d_to_c_positions=0),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    await signal_bus.publish(_signal(activate_time=1_000, direction=Direction.D_TO_C))

    assert [decision.direction for decision in decisions] == [Direction.D_TO_C]


async def test_strategy_engine_uses_initial_dex_token0_positions(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(max_positions=2, initial_d_to_c_positions=2),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    await signal_bus.publish(_signal(activate_time=1_000, direction=Direction.C_TO_D))
    await signal_bus.publish(_signal(activate_time=31_000, direction=Direction.C_TO_D))
    await signal_bus.publish(_signal(activate_time=61_000, direction=Direction.C_TO_D))

    assert [decision.direction for decision in decisions] == [
        Direction.C_TO_D,
        Direction.C_TO_D,
    ]


async def test_strategy_engine_cools_down_consecutive_same_direction(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(max_positions=2, initial_d_to_c_positions=0),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    await signal_bus.publish(_signal(activate_time=1_000, direction=Direction.D_TO_C))
    await signal_bus.publish(_signal(activate_time=30_999, direction=Direction.D_TO_C))
    await signal_bus.publish(_signal(activate_time=31_000, direction=Direction.D_TO_C))

    assert [decision.direction for decision in decisions] == [
        Direction.D_TO_C,
        Direction.D_TO_C,
    ]


async def test_strategy_engine_ignores_direction_after_max_positions(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(max_positions=2),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    await signal_bus.publish(_signal(activate_time=1_000, direction=Direction.D_TO_C))
    await signal_bus.publish(_signal(activate_time=31_000, direction=Direction.D_TO_C))
    await signal_bus.publish(_signal(activate_time=61_000, direction=Direction.D_TO_C))

    assert len(decisions) == 2
    assert [decision.direction for decision in decisions] == [
        Direction.D_TO_C,
        Direction.D_TO_C,
    ]


async def test_strategy_engine_rounds_cex_precision_before_trade_decision(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(
            cex_quantity_precision=2,
            cex_price_precision=3,
            quantity=Decimal("2.567"),
            initial_d_to_c_positions=1,
        ),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus).start()

    signal = _signal()
    await signal_bus.publish(signal)

    assert decisions[0].cextrade.quantity == Decimal("2.56")
    assert decisions[0].dextrade.quantity == Decimal("2.56")
    assert decisions[0].cextrade.acceptable_price == Decimal("101.050")


async def test_strategy_engine_rounds_cex_sell_price_up(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(cex_price_precision=3),
    )
    monkeypatch.setattr("cex_dex_arbitrage.components.strategy_engine.time.time_ns", lambda: 1_700_000_000_123_000_000)
    signal = _signal()
    signal = ArbSignal(
        bps=signal.bps,
        direction=Direction.D_TO_C,
        activate_time=signal.activate_time,
        tick1=signal.tick1,
        tick2=signal.tick2,
    )

    decision = StrategyEngine(
        signal_bus=Bus("signal-test"),
        trade_bus=Bus("trade-test"),
    )._build_decision(signal)

    assert decision is not None
    assert decision.cextrade.acceptable_price == Decimal("98.951")


async def test_strategy_engine_stop_prevents_new_decisions(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.strategy_engine.settings",
        _settings(),
    )
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    trade_bus: Bus[TradeDecision] = Bus("trade-test")
    decisions: list[TradeDecision] = []

    async def collect(decision: TradeDecision) -> None:
        decisions.append(decision)

    trade_bus.subscribe(collect)
    strategy = StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus)
    strategy.start()
    strategy.stop()

    await signal_bus.publish(_signal())

    assert decisions == []
