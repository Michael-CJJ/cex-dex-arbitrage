import json
from decimal import Decimal

from cex_dex_arbitrage.models.signal import Direction
from cex_dex_arbitrage.models.trade import CexTrade, DexTrade, TradeDecision
from cex_dex_arbitrage.trading import dex_trade as dex_trade_module


TOKEN0 = "0x0000000000000000000000000000000000000001"
TOKEN1 = "0x0000000000000000000000000000000000000002"


def _settings():
    return type(
        "S",
        (),
        {
            "pool_token0_address": TOKEN0,
            "pool_token1_address": TOKEN1,
        },
    )()


def _decision(direction: str = "sell") -> TradeDecision:
    dex_acceptable_price = Decimal("101.9490") if direction == "sell" else Decimal("102.0510")
    return TradeDecision(
        bps=Decimal("100"),
        direction=Direction.C_TO_D,
        activate_time=1,
        decision_generated_time=2,
        cextrade=CexTrade(
            direction="buy",
            quantity=Decimal("2"),
            expected_price=Decimal("101"),
            acceptable_price=Decimal("101.0505"),
        ),
        dextrade=DexTrade(
            direction=direction,
            quantity=Decimal("2"),
            expected_price=Decimal("102"),
            acceptable_price=dex_acceptable_price,
        ),
    )


async def test_dex_trade_sells_token0_target(monkeypatch) -> None:
    calls = []
    to_thread_calls = []

    def fake_swap(in_token, zero_for_one, amount_specified, sqrt_price_limit_x96):
        calls.append((in_token, zero_for_one, amount_specified, sqrt_price_limit_x96))
        return "0xtx"

    async def fake_to_thread(fn, /, *args, **kwargs):
        to_thread_calls.append((fn, args, kwargs))
        return fn(*args, **kwargs)

    monkeypatch.setattr(dex_trade_module, "settings", _settings())
    monkeypatch.setattr(dex_trade_module, "swap", fake_swap)
    monkeypatch.setattr(dex_trade_module.asyncio, "to_thread", fake_to_thread)
    dex_trade_module.initialize_dex_trade()

    decision = _decision("sell")
    expected_limit = dex_trade_module._sqrt_price_limit_from_price(
        decision.dextrade.acceptable_price
    )

    assert await dex_trade_module.dex_trade(decision) == "0xtx"
    assert to_thread_calls == [
        (
            fake_swap,
            (),
            {
                "in_token": TOKEN0,
                "zero_for_one": True,
                "amount_specified": 2 * 10**18,
                "sqrt_price_limit_x96": expected_limit,
            },
        )
    ]
    assert calls == [
        (
            TOKEN0,
            True,
            2 * 10**18,
            expected_limit,
        )
    ]


async def test_dex_trade_buys_token0_target(monkeypatch) -> None:
    calls = []

    def fake_swap(in_token, zero_for_one, amount_specified, sqrt_price_limit_x96):
        calls.append((in_token, zero_for_one, amount_specified, sqrt_price_limit_x96))
        return "0xtx"

    monkeypatch.setattr(dex_trade_module, "settings", _settings())
    monkeypatch.setattr(dex_trade_module, "swap", fake_swap)
    dex_trade_module.initialize_dex_trade()

    decision = _decision("buy")
    expected_limit = dex_trade_module._sqrt_price_limit_from_price(
        decision.dextrade.acceptable_price
    )

    assert await dex_trade_module.dex_trade(decision) == "0xtx"
    assert calls == [
        (
            TOKEN1,
            False,
            -2 * 10**18,
            expected_limit,
        )
    ]


def test_initialize_dex_nonce_writes_pending_nonce(monkeypatch, tmp_path) -> None:
    nonce_path = tmp_path / "nonce.json"

    class FakeAccount:
        address = "0x8d9f48afe95739518204a2e0e10f1503ea059acf"

    class FakeAccountFactory:
        @staticmethod
        def from_key(private_key: str) -> FakeAccount:
            assert private_key == "private-key"
            return FakeAccount()

    class FakeEth:
        @staticmethod
        def get_transaction_count(address: str, block_identifier: str) -> int:
            assert address == "0x8D9F48AfE95739518204a2E0e10F1503ea059ACf"
            assert block_identifier == "pending"
            return 12

    class FakeWeb3:
        eth = FakeEth()

        def __init__(self, provider) -> None:
            self.provider = provider

        @staticmethod
        def HTTPProvider(rpc_url: str) -> str:
            assert rpc_url == "https://rpc.example"
            return rpc_url

        @staticmethod
        def to_checksum_address(address: str) -> str:
            return "0x8D9F48AfE95739518204a2E0e10F1503ea059ACf"

        def is_connected(self) -> bool:
            return True

    monkeypatch.setattr(
        dex_trade_module,
        "settings",
        type(
            "S",
            (),
            {
                "bsc_private_key": "private-key",
                "chainstack_https_url": "https://rpc.example",
            },
        )(),
    )
    monkeypatch.setattr(dex_trade_module, "NONCE_PATH", nonce_path)
    monkeypatch.setattr(dex_trade_module, "Account", FakeAccountFactory)
    monkeypatch.setattr(dex_trade_module, "Web3", FakeWeb3)

    dex_trade_module.initialize_dex_nonce()

    state = json.loads(nonce_path.read_text(encoding="utf-8"))
    assert state["network"] == "mainnet"
    assert state["nonces"] == {"0x8D9F48AfE95739518204a2E0e10F1503ea059ACf": 12}
    assert "updated_at" in state
