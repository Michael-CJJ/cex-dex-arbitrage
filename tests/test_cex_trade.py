from decimal import Decimal

from cex_dex_arbitrage.models.signal import Direction
from cex_dex_arbitrage.models.trade import CexTrade, DexTrade, TradeDecision
from cex_dex_arbitrage.trading.cex_trade import cex_trade


async def test_cex_trade_places_fok_order_at_acceptable_price(monkeypatch) -> None:
    calls = []

    async def fake_place_fok_limit_order(**kwargs):
        calls.append(kwargs)
        return {"status": 200}

    monkeypatch.setattr(
        "cex_dex_arbitrage.trading.cex_trade.settings",
        type("S", (), {"binance_futures_symbol": "BUSDT"})(),
    )
    monkeypatch.setattr(
        "cex_dex_arbitrage.trading.cex_trade.place_fok_limit_order",
        fake_place_fok_limit_order,
    )

    decision = TradeDecision(
        bps=Decimal("1"),
        direction=Direction.C_TO_D,
        activate_time=1,
        decision_generated_time=2,
        cextrade=CexTrade(
            direction="buy",
            quantity=Decimal("3"),
            expected_price=Decimal("0.63"),
            acceptable_price=Decimal("0.631"),
        ),
        dextrade=DexTrade(
            direction="sell",
            quantity=Decimal("3"),
            expected_price=Decimal("0.63"),
            acceptable_price=Decimal("0.629"),
        ),
    )

    assert await cex_trade(decision) == {"status": 200}
    assert calls == [
        {
            "symbol": "BUSDT",
            "side": "BUY",
            "quantity": Decimal("3"),
            "price": Decimal("0.631"),
        }
    ]
