import json
import time
from collections.abc import Callable
from decimal import Decimal, localcontext
from typing import Any

from web3 import Web3

from cex_dex_arbitrage.config import settings
from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components.bnb_price_cache import BNBPriceCache
from cex_dex_arbitrage.models.market import MarketTick, SwapTick
from cex_dex_arbitrage.models.result import DexFill, TradeResult
from cex_dex_arbitrage.utils.ws_client import WSClient

# PancakeSwap V3 Swap(address,address,int256,int256,uint160,uint128,int24)
SWAP_TOPIC0 = "0x19b47279256b2a23a1665c810c8d55a1758940ee09377d4f8d26497a3577dc83"

Q96 = Decimal(1 << 96)  # Build from int to avoid Decimal's default precision.


def _words(data_hex: str) -> list[str]:
    data = data_hex.lower().removeprefix("0x")
    return [data[i : i + 64] for i in range(0, len(data), 64)]


def _decode_uint(word: str) -> int:
    return int(word, 16)


def _decode_int(word: str, bits: int = 256) -> int:
    value = int(word, 16) & ((1 << bits) - 1)
    sign_bit = 1 << (bits - 1)
    return value - (1 << bits) if value & sign_bit else value


def _price_token0_in_token1(sqrt_price_x96: int) -> Decimal:
    """Convert sqrtPriceX96 to token0 price in token1 units."""
    with localcontext() as ctx:
        ctx.prec = 80
        sqrt_price = Decimal(sqrt_price_x96) / Q96
        return sqrt_price * sqrt_price


def _token_quantity(raw_amount: int) -> Decimal:
    return Decimal(abs(raw_amount)) / Decimal(10**18)


def _average_fill_price_token0_in_token1(amount0: int, amount1: int) -> Decimal:
    return Decimal(abs(amount1)) / Decimal(abs(amount0))


def _decode_swap_log(log_obj: dict[str, Any]) -> dict[str, Any] | None:
    """Decode sender, amount0, amount1, and sqrt_price_x96 from a Swap log."""
    topics = [str(t).lower() for t in log_obj.get("topics") or []]
    if len(topics) < 2 or topics[0] != SWAP_TOPIC0:
        return None

    data_words = _words(str(log_obj.get("data") or "0x"))
    if len(data_words) < 5:
        return None

    sender_hex = topics[1].removeprefix("0x").rjust(64, "0")
    return {
        "sender": "0x" + sender_hex[-40:],
        "amount0": _decode_int(data_words[0], 256),
        "amount1": _decode_int(data_words[1], 256),
        "sqrt_price_x96": _decode_uint(data_words[2]),
    }


class PancakeSwapLogsSource:
    """Subscribe to PancakeSwap V3 Swap logs for one pool.

    All swaps update market_bus. Swaps sent by the configured executor contract
    are also routed to result_bus as DEX fills.
    """

    def __init__(
        self,
        market_bus: Bus[MarketTick],
        result_bus: Bus[TradeResult],
        bnb_price_cache: BNBPriceCache | None = None,
        gas_lookup: Callable[[str], tuple[int, int]] | None = None,
    ) -> None:
        self.market_bus = market_bus
        self.result_bus = result_bus
        self.contract_address = settings.contract_address
        self.bnb_price_cache = bnb_price_cache
        self.gas_lookup = gas_lookup

    async def _on_connect(self, ws) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": [
                "logs",
                {
                    "address": settings.pancake_v3_pool_address.lower(),
                    "topics": [SWAP_TOPIC0],
                },
            ],
        }
        await ws.send(json.dumps(req))

    async def run(self) -> None:
        client = WSClient(
            url=settings.chainstack_wss_url,
            on_message=self._handle,
            on_connect=self._on_connect,
            name="pcs_swap",
        )
        await client.run()

    async def _handle(self, raw: str) -> None:
        msg = json.loads(raw)
        if msg.get("method") != "eth_subscription":
            return

        result = (msg.get("params") or {}).get("result") or {}
        if result.get("removed") is True:
            return

        decoded = _decode_swap_log(result)
        if decoded is None:
            return

        receive_time = time.time_ns() // 1_000_000

        if decoded["amount0"] > 0:
            direction = "0->1"
            quantity = _token_quantity(decoded["amount0"])
        else:
            direction = "1->0"
            quantity = _token_quantity(decoded["amount1"])

        price = _price_token0_in_token1(decoded["sqrt_price_x96"])

        await self.market_bus.publish(SwapTick(
            direction=direction,
            quantity=quantity,
            price=price,
            send_time=receive_time,
            receive_time=receive_time,
        ))

        if self.contract_address and decoded["sender"].lower() == self.contract_address.lower():
            txhash = str(result.get("transactionHash") or "")
            gas_used, gas_price_wei = self._gas_cost(txhash)
            await self.result_bus.publish(DexFill(
                price=_average_fill_price_token0_in_token1(
                    decoded["amount0"],
                    decoded["amount1"],
                ),
                quantity=_token_quantity(decoded["amount0"]),
                txhash=txhash,
                gas=gas_used,
                gas_price_wei=gas_price_wei,
                gas_bnb=self._gas_bnb(gas_used, gas_price_wei),
                gas_usd=self._gas_usd(gas_used, gas_price_wei),
                send_time=receive_time,
                receive_time=receive_time,
            ))

    def _gas_cost(self, txhash: str) -> tuple[int, int]:
        if self.gas_lookup is not None:
            return self.gas_lookup(txhash)

        w3 = Web3(Web3.HTTPProvider(settings.chainstack_https_url))
        receipt = w3.eth.get_transaction_receipt(txhash)
        gas_price_wei = receipt.get("effectiveGasPrice")
        if gas_price_wei is None:
            tx = w3.eth.get_transaction(txhash)
            gas_price_wei = tx["gasPrice"]
        return int(receipt["gasUsed"]), int(gas_price_wei)

    def _gas_bnb(self, gas_used: int, gas_price_wei: int) -> Decimal:
        if self.bnb_price_cache is None:
            return Decimal(gas_used) * Decimal(gas_price_wei) / Decimal(10**18)
        return self.bnb_price_cache.gas_bnb(gas_used, gas_price_wei)

    def _gas_usd(self, gas_used: int, gas_price_wei: int) -> Decimal | None:
        if self.bnb_price_cache is None:
            return None
        return self.bnb_price_cache.gas_usd(gas_used, gas_price_wei)
