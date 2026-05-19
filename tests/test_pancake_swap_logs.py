import json
import time
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.bnb_price_cache import BNBPriceCache
from cex_dex_arbitrage.models.market import MarketTick, SwapTick
from cex_dex_arbitrage.models.result import DexFill, TradeResult
from cex_dex_arbitrage.sources.pancake_swap_logs import (
    SWAP_TOPIC0,
    PancakeSwapLogsSource,
    _decode_swap_log,
)


# ---- helpers ------------------------------------------------------------


def _word(value: int) -> str:
    """Encode a signed 256-bit integer as one ABI word without the 0x prefix."""
    if value < 0:
        value = (1 << 256) + value
    return f"{value:064x}"


def _sender_topic(addr: str) -> str:
    return "0x" + addr.lower().removeprefix("0x").rjust(64, "0")


def _make_log(sender: str, amount0: int, amount1: int, sqrt_price_x96: int) -> dict:
    return {
        "topics": [
            SWAP_TOPIC0,
            _sender_topic(sender),
            "0x" + "0" * 64,
        ],
        "data": (
            "0x"
            + _word(amount0)
            + _word(amount1)
            + _word(sqrt_price_x96)
            + _word(0)  # liquidity
            + _word(0)  # tick
        ),
        "blockNumber": "0x1",
        "transactionHash": "0x" + "ab" * 32,
        "logIndex": "0x0",
        "removed": False,
    }


def _wrap_subscription(log_obj: dict) -> str:
    return json.dumps({
        "jsonrpc": "2.0",
        "method": "eth_subscription",
        "params": {"subscription": "0xsubid", "result": log_obj},
    })


def _make_source(
    bnb_price_cache=None,
    gas_lookup=None,
) -> tuple[PancakeSwapLogsSource, list[MarketTick], list[TradeResult]]:
    market_bus: Bus[MarketTick] = Bus("m")
    result_bus: Bus[TradeResult] = Bus("r")
    market: list[MarketTick] = []
    result: list[TradeResult] = []

    async def m(t: MarketTick) -> None:
        market.append(t)

    async def r(t: TradeResult) -> None:
        result.append(t)

    market_bus.subscribe(m)
    result_bus.subscribe(r)

    return (
        PancakeSwapLogsSource(
            market_bus=market_bus,
            result_bus=result_bus,
            bnb_price_cache=bnb_price_cache,
            gas_lookup=gas_lookup,
        ),
        market,
        result,
    )


SQRT_PRICE_AT_1 = 1 << 96  # sqrt(1) * 2^96, so price is 1.0.


def _source_settings(contract_addr: str):
    return type(
        "S",
        (),
        {
            "contract_address": contract_addr,
        },
    )()


ONE_E18 = 10**18


# ---- decoder ------------------------------------------------------------


async def test_decode_swap_log_extracts_fields() -> None:
    sender = "0x1234567890abcdef1234567890abcdef12345678"
    log_obj = _make_log(sender, ONE_E18, -ONE_E18, SQRT_PRICE_AT_1)
    decoded = _decode_swap_log(log_obj)
    assert decoded is not None
    assert decoded["sender"] == sender.lower()
    assert decoded["amount0"] == ONE_E18
    assert decoded["amount1"] == -ONE_E18
    assert decoded["sqrt_price_x96"] == SQRT_PRICE_AT_1


async def test_decode_swap_log_returns_none_for_other_topic() -> None:
    log_obj = _make_log("0x" + "11" * 20, 1, -1, SQRT_PRICE_AT_1)
    log_obj["topics"][0] = "0x" + "00" * 32
    assert _decode_swap_log(log_obj) is None


# ---- _handle pipeline ---------------------------------------------------


async def test_handle_publishes_swap_tick_for_zero_to_one() -> None:
    source, market, _ = _make_source()
    log_obj = _make_log(
        sender="0x" + "11" * 20,
        amount0=ONE_E18,
        amount1=-2 * ONE_E18,
        sqrt_price_x96=SQRT_PRICE_AT_1,
    )

    before_ms = time.time_ns() // 1_000_000
    await source._handle(_wrap_subscription(log_obj))
    after_ms = time.time_ns() // 1_000_000

    assert len(market) == 1
    tick = market[0]
    assert isinstance(tick, SwapTick)
    assert tick.direction == "0->1"
    assert tick.quantity == Decimal("1")
    assert tick.price == Decimal("1")
    assert tick.send_time == tick.receive_time
    assert before_ms <= tick.receive_time <= after_ms


async def test_handle_publishes_swap_tick_for_one_to_zero() -> None:
    source, market, _ = _make_source()
    log_obj = _make_log(
        sender="0x" + "11" * 20,
        amount0=-2 * ONE_E18,
        amount1=ONE_E18,
        sqrt_price_x96=SQRT_PRICE_AT_1,
    )
    await source._handle(_wrap_subscription(log_obj))

    assert len(market) == 1
    tick = market[0]
    assert tick.direction == "1->0"
    assert tick.quantity == Decimal("1")


async def test_handle_ignores_non_subscription_message() -> None:
    source, market, result = _make_source()
    ack = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "0xsubid"})
    await source._handle(ack)
    assert market == []
    assert result == []


async def test_handle_ignores_removed_logs() -> None:
    source, market, result = _make_source()
    log_obj = _make_log("0x" + "11" * 20, ONE_E18, -ONE_E18, SQRT_PRICE_AT_1)
    log_obj["removed"] = True
    await source._handle(_wrap_subscription(log_obj))
    assert market == []
    assert result == []


# ---- result_bus routing ------------------------------------------------


async def test_handle_routes_self_contract_to_result_bus(monkeypatch) -> None:
    contract_addr = "0xabcdefABCDEFabcdefABCDEFabcdefABCDEF1234"
    monkeypatch.setattr(
        "cex_dex_arbitrage.sources.pancake_swap_logs.settings",
        _source_settings(contract_addr),
    )
    bnb_price_cache = BNBPriceCache(market_bus=Bus("bnb-test"))
    bnb_price_cache.mid_price = Decimal("600")
    source, market, result = _make_source(
        bnb_price_cache=bnb_price_cache,
        gas_lookup=lambda txhash: (134475, 100000000),
    )
    log_obj = _make_log(
        sender=contract_addr,
        amount0=ONE_E18,
        amount1=-2 * ONE_E18,
        sqrt_price_x96=SQRT_PRICE_AT_1,
    )
    before_ms = time.time_ns() // 1_000_000
    await source._handle(_wrap_subscription(log_obj))
    after_ms = time.time_ns() // 1_000_000

    assert len(market) == 1
    assert len(result) == 1
    fill = result[0]
    assert isinstance(fill, DexFill)
    assert fill.price == Decimal("2")
    assert fill.quantity == Decimal("1")
    assert fill.txhash == "0x" + "ab" * 32
    assert fill.gas == 134475
    assert fill.gas_price_wei == 100000000
    assert fill.gas_bnb == Decimal("0.0000134475")
    assert fill.gas_usd == Decimal("0.0080685000")
    assert fill.send_time == fill.receive_time
    assert before_ms <= fill.receive_time <= after_ms


async def test_handle_skips_result_bus_for_other_contract(monkeypatch) -> None:
    monkeypatch.setattr(
        "cex_dex_arbitrage.sources.pancake_swap_logs.settings",
        _source_settings("0x" + "ab" * 20),
    )
    source, market, result = _make_source()
    log_obj = _make_log(
        sender="0x" + "cd" * 20,
        amount0=ONE_E18,
        amount1=-ONE_E18,
        sqrt_price_x96=SQRT_PRICE_AT_1,
    )
    await source._handle(_wrap_subscription(log_obj))

    assert len(market) == 1
    assert len(result) == 0
