import hashlib
import hmac
import json
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.result import CexFill, CexWrong, TradeResult
from cex_dex_arbitrage.sources.binance_orderfill import (
    BinanceOrderFillSource,
    place_fok_limit_order,
    set_binance_orderfill_source,
)


async def test_place_fok_limit_order_sends_signed_order_request(monkeypatch) -> None:
    sent: list[str] = []
    result_bus: Bus[TradeResult] = Bus("result-test")

    class FakeWs:
        async def send(self, raw: str) -> None:
            sent.append(raw)

    monkeypatch.setattr(
        "cex_dex_arbitrage.sources.binance_orderfill.settings",
        type(
            "S",
            (),
            {
                "binance_api_key": "api-key",
                "binance_api_secret": "secret",
            },
        )(),
    )
    monkeypatch.setattr("cex_dex_arbitrage.sources.binance_orderfill.time.time", lambda: 1700000000.123)

    source = BinanceOrderFillSource(result_bus=result_bus)
    source._ws = FakeWs()
    source._connected.set()

    response = await source.place_fok_limit_order(
        symbol="BUSDT",
        side="BUY",
        quantity=Decimal("2.5"),
        price=Decimal("0.63181575000"),
    )

    request = json.loads(sent[0])
    params = request["params"]
    unsigned = {key: value for key, value in params.items() if key != "signature"}
    payload = "&".join(f"{key}={unsigned[key]}" for key in sorted(unsigned))
    expected_signature = hmac.new(
        b"secret",
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    assert request["method"] == "order.place"
    assert response == {
        "id": request["id"],
        "method": "order.place",
        "status": "SENT",
    }
    assert params == {
        "apiKey": "api-key",
        "symbol": "BUSDT",
        "side": "BUY",
        "type": "LIMIT",
        "timeInForce": "FOK",
        "quantity": "2.5",
        "price": "0.63181575000",
        "newOrderRespType": "RESULT",
        "timestamp": 1700000000123,
        "signature": expected_signature,
    }


async def test_order_response_publishes_cex_fill(monkeypatch) -> None:
    result_bus: Bus[TradeResult] = Bus("result-test")
    fills: list[TradeResult] = []

    async def collect(fill: TradeResult) -> None:
        fills.append(fill)

    result_bus.subscribe(collect)
    source = BinanceOrderFillSource(result_bus=result_bus)
    monkeypatch.setattr("cex_dex_arbitrage.sources.binance_orderfill.time.time_ns", lambda: 1_700_000_000_123_000_000)

    await source._handle_message(json.dumps({
        "id": "order-1",
        "status": 200,
        "result": {
            "symbol": "BUSDT",
            "orderId": 42,
            "clientOrderId": "client-42",
            "status": "FILLED",
            "side": "SELL",
            "avgPrice": "0.631",
            "executedQty": "3",
            "cumQuote": "1.893",
            "updateTime": 1_700_000_000_100,
        },
    }))

    assert fills == [
        CexFill(
            symbol="BUSDT",
            order_id=42,
            client_order_id="client-42",
            status="FILLED",
            direction="sell",
            price=Decimal("0.631"),
            quantity=Decimal("3"),
            quote_quantity=Decimal("1.893"),
            send_time=1_700_000_000_100,
            receive_time=1_700_000_000_123,
        )
    ]


async def test_expired_order_response_publishes_cex_wrong(monkeypatch) -> None:
    result_bus: Bus[TradeResult] = Bus("result-test")
    results: list[TradeResult] = []

    async def collect(result: TradeResult) -> None:
        results.append(result)

    result_bus.subscribe(collect)
    source = BinanceOrderFillSource(result_bus=result_bus)
    monkeypatch.setattr("cex_dex_arbitrage.sources.binance_orderfill.time.time_ns", lambda: 1_700_000_000_123_000_000)

    raw = {
        "id": "order-1",
        "status": 200,
        "result": {
            "symbol": "BUSDT",
            "orderId": 43,
            "clientOrderId": "client-43",
            "status": "EXPIRED",
            "side": "BUY",
            "price": "0.631",
            "origQty": "3",
            "executedQty": "0",
            "cumQuote": "0",
            "updateTime": 1_700_000_000_100,
        },
    }
    await source._handle_message(json.dumps(raw))

    assert results == [
        CexWrong(
            symbol="BUSDT",
            order_id=43,
            client_order_id="client-43",
            status="EXPIRED",
            direction="buy",
            price=Decimal("0.631"),
            quantity=Decimal("3"),
            executed_quantity=Decimal("0"),
            quote_quantity=Decimal("0"),
            reason="order expired without fill",
            raw=raw,
            send_time=1_700_000_000_100,
            receive_time=1_700_000_000_123,
        )
    ]


async def test_api_error_response_publishes_cex_wrong(monkeypatch) -> None:
    result_bus: Bus[TradeResult] = Bus("result-test")
    results: list[TradeResult] = []

    async def collect(result: TradeResult) -> None:
        results.append(result)

    result_bus.subscribe(collect)
    source = BinanceOrderFillSource(result_bus=result_bus)
    monkeypatch.setattr("cex_dex_arbitrage.sources.binance_orderfill.time.time_ns", lambda: 1_700_000_000_123_000_000)
    raw = {
        "id": "order-1",
        "status": 400,
        "error": {
            "code": -2019,
            "msg": "Margin is insufficient.",
        },
    }

    await source._handle_message(json.dumps(raw))

    assert results == [
        CexWrong(
            symbol=None,
            order_id=None,
            client_order_id=None,
            status="API_ERROR",
            direction=None,
            price=None,
            quantity=None,
            executed_quantity=None,
            quote_quantity=None,
            reason="-2019: Margin is insufficient.",
            raw=raw,
            send_time=None,
            receive_time=1_700_000_000_123,
        )
    ]


async def test_global_place_fok_limit_order_uses_configured_source(monkeypatch) -> None:
    calls = []

    class FakeSource:
        async def place_fok_limit_order(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True}

    set_binance_orderfill_source(FakeSource())

    assert await place_fok_limit_order(
        symbol="BUSDT",
        side="BUY",
        quantity=Decimal("1"),
        price=Decimal("0.5"),
    ) == {"ok": True}
    assert calls == [
        {
            "symbol": "BUSDT",
            "side": "BUY",
            "quantity": Decimal("1"),
            "price": Decimal("0.5"),
        }
    ]
