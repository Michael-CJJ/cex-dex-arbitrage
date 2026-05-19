from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.arb_calculator import ArbCalculator
from cex_dex_arbitrage.models.market import BNBPrice, MarketTick, OrderBookTick, SwapTick
from cex_dex_arbitrage.models.signal import ArbSignal, Direction


def _ob(
    bid_price: str = "99",
    ask_price: str = "101",
    bid_quantity: str = "3",
    ask_quantity: str = "2",
    send_time: int = 1,
) -> OrderBookTick:
    return OrderBookTick(
        bid_price=Decimal(bid_price),
        ask_price=Decimal(ask_price),
        bid_quantity=Decimal(bid_quantity),
        ask_quantity=Decimal(ask_quantity),
        send_time=send_time,
        receive_time=1,
    )


def _swap(price: str, quantity: str = "5", send_time: int = 2) -> SwapTick:
    return SwapTick(
        direction="0->1",
        quantity=Decimal(quantity),
        price=Decimal(price),
        send_time=send_time,
        receive_time=2,
    )


def _settings(base_bps: str = "0", threshold_bps: str = "10", pool_bnb: bool = False):
    return type(
        "S",
        (),
        {
            "base_bps": Decimal(base_bps),
            "threshold_bps": Decimal(threshold_bps),
            "pool_bnb": pool_bnb,
        },
    )()


def _make_calculator() -> tuple[Bus[MarketTick], list[ArbSignal]]:
    market_bus: Bus[MarketTick] = Bus("market-test")
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    signals: list[ArbSignal] = []

    async def collect(signal: ArbSignal) -> None:
        signals.append(signal)

    signal_bus.subscribe(collect)
    ArbCalculator(market_bus=market_bus, signal_bus=signal_bus).start()
    return market_bus, signals


def _make_stoppable_calculator() -> tuple[Bus[MarketTick], list[ArbSignal], ArbCalculator]:
    market_bus: Bus[MarketTick] = Bus("market-test")
    signal_bus: Bus[ArbSignal] = Bus("signal-test")
    signals: list[ArbSignal] = []

    async def collect(signal: ArbSignal) -> None:
        signals.append(signal)

    signal_bus.subscribe(collect)
    calculator = ArbCalculator(market_bus=market_bus, signal_bus=signal_bus)
    calculator.start()
    return market_bus, signals, calculator


def _assert_signal(
    signal: ArbSignal,
    *,
    bps: Decimal,
    direction: Direction,
    activate_time: int,
    tick1: OrderBookTick,
    tick2: SwapTick,
) -> None:
    assert signal.bps == bps
    assert signal.direction == direction
    assert signal.activate_time == activate_time
    assert signal.tick1 == tick1
    assert signal.tick2 == tick2


async def test_waits_for_both_market_sides(monkeypatch) -> None:
    monkeypatch.setattr("cex_dex_arbitrage.components.arb_calculator.settings", _settings())
    market_bus, signals = _make_calculator()

    await market_bus.publish(_ob())

    assert signals == []


async def test_publishes_c_to_d_when_dex_above_base_plus_threshold(monkeypatch) -> None:
    monkeypatch.setattr("cex_dex_arbitrage.components.arb_calculator.settings", _settings())
    market_bus, signals = _make_calculator()
    ob = _ob(ask_quantity="2")
    swap = _swap("102", quantity="5")

    await market_bus.publish(ob)
    await market_bus.publish(swap)

    assert len(signals) == 1
    _assert_signal(
        signals[0],
        bps=Decimal("200"),
        direction=Direction.C_TO_D,
        activate_time=2,
        tick1=ob,
        tick2=swap,
    )


async def test_publishes_d_to_c_when_dex_below_base_minus_threshold(monkeypatch) -> None:
    monkeypatch.setattr("cex_dex_arbitrage.components.arb_calculator.settings", _settings())
    market_bus, signals = _make_calculator()
    ob = _ob(bid_quantity="3")
    swap = _swap("98", quantity="5")

    await market_bus.publish(ob)
    await market_bus.publish(swap)

    assert len(signals) == 1
    _assert_signal(
        signals[0],
        bps=Decimal("-200"),
        direction=Direction.D_TO_C,
        activate_time=2,
        tick1=ob,
        tick2=swap,
    )


async def test_does_not_publish_inside_threshold(monkeypatch) -> None:
    monkeypatch.setattr("cex_dex_arbitrage.components.arb_calculator.settings", _settings(threshold_bps="20"))
    market_bus, signals = _make_calculator()

    await market_bus.publish(_ob())
    await market_bus.publish(_swap("100.2"))

    assert signals == []


async def test_base_bps_shifts_neutral_spread(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.arb_calculator.settings",
        _settings(base_bps="100", threshold_bps="25"),
    )
    market_bus, signals = _make_calculator()
    ob = _ob()
    first_swap = _swap("101.2")
    second_swap = _swap("101.4")

    await market_bus.publish(ob)
    await market_bus.publish(first_swap)
    await market_bus.publish(second_swap)

    assert len(signals) == 1
    _assert_signal(
        signals[0],
        bps=Decimal("140.0"),
        direction=Direction.C_TO_D,
        activate_time=2,
        tick1=ob,
        tick2=second_swap,
    )


async def test_pool_bnb_waits_for_bnb_price(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.arb_calculator.settings",
        _settings(pool_bnb=True),
    )
    market_bus, signals = _make_calculator()

    await market_bus.publish(_ob())
    await market_bus.publish(_swap("0.2"))

    assert signals == []


async def test_ignores_bnb_price_ticks_when_pool_is_not_bnb(monkeypatch) -> None:
    monkeypatch.setattr("cex_dex_arbitrage.components.arb_calculator.settings", _settings())
    market_bus, signals = _make_calculator()

    await market_bus.publish(_ob())
    await market_bus.publish(_swap("102"))
    assert len(signals) == 1

    await market_bus.publish(BNBPrice(mid_price=Decimal("510")))
    assert len(signals) == 1


async def test_pool_bnb_converts_dex_price_with_bnb_mid(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.components.arb_calculator.settings",
        _settings(pool_bnb=True),
    )
    market_bus, signals = _make_calculator()
    ob = _ob(ask_quantity="2")
    swap = _swap("0.2", quantity="5")

    await market_bus.publish(ob)
    await market_bus.publish(swap)
    await market_bus.publish(BNBPrice(mid_price=Decimal("510")))

    assert len(signals) == 1
    _assert_signal(
        signals[0],
        bps=Decimal("200.0"),
        direction=Direction.C_TO_D,
        activate_time=2,
        tick1=ob,
        tick2=swap,
    )


async def test_signal_activate_time_uses_later_market_send_time(monkeypatch) -> None:
    monkeypatch.setattr("cex_dex_arbitrage.components.arb_calculator.settings", _settings())
    market_bus, signals = _make_calculator()

    await market_bus.publish(_ob(send_time=12))
    await market_bus.publish(_swap("102", send_time=10))

    assert signals[0].activate_time == 12


async def test_stop_prevents_new_signals(monkeypatch) -> None:
    monkeypatch.setattr("cex_dex_arbitrage.components.arb_calculator.settings", _settings())
    market_bus, signals, calculator = _make_stoppable_calculator()

    await market_bus.publish(_ob())
    calculator.stop()
    await market_bus.publish(_swap("102"))

    assert signals == []
