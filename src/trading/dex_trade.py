import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR, localcontext
from pathlib import Path

from eth_account import Account
from web3 import Web3

from cex_dex_arbitrage.config import settings
from cex_dex_arbitrage.models.trade import TradeDecision
from cex_dex_arbitrage.utils.logger import get_logger

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[3]
NONCE_PATH = ROOT / "data" / "nonce_state.json"

MIN_SQRT_RATIO = 4295128739
MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342
Q96 = Decimal(1 << 96)
_nonce_lock = asyncio.Lock()

POOL_TOKEN0_ADDRESS = ""
POOL_TOKEN1_ADDRESS = ""

EXEC_ABI = [
    {
        "type": "function",
        "name": "swap",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "pool", "type": "address"},
            {"name": "recipient", "type": "address"},
            {"name": "zeroForOne", "type": "bool"},
            {"name": "amountSpecified", "type": "int256"},
            {"name": "sqrtPriceLimitX96", "type": "uint160"},
            {"name": "inToken", "type": "address"},
        ],
        "outputs": [
            {"name": "amount0", "type": "int256"},
            {"name": "amount1", "type": "int256"},
        ],
    },
]


def initialize_dex_trade() -> None:
    global POOL_TOKEN0_ADDRESS
    global POOL_TOKEN1_ADDRESS

    POOL_TOKEN0_ADDRESS = Web3.to_checksum_address(settings.pool_token0_address)
    POOL_TOKEN1_ADDRESS = Web3.to_checksum_address(settings.pool_token1_address)


def initialize_dex_nonce() -> None:
    account = Account.from_key(settings.bsc_private_key)
    address = Web3.to_checksum_address(account.address)
    w3 = Web3(Web3.HTTPProvider(settings.chainstack_https_url))
    if not w3.is_connected():
        raise RuntimeError("cannot connect to CHAINSTACK_HTTPS_URL")

    nonce = w3.eth.get_transaction_count(address, "pending")
    save_nonce_state(address, nonce)
    log.info("loaded mainnet pending nonce")


def load_nonce_state() -> dict:
    if not NONCE_PATH.exists():
        return {"network": "mainnet", "nonces": {}}

    with NONCE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def nonce_for_account(address: str) -> int:
    state = load_nonce_state()
    return int(state["nonces"][address])


def save_nonce_state(address: str, nonce: int) -> None:
    NONCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    state = load_nonce_state()
    state["network"] = "mainnet"
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    state["nonces"][address] = nonce

    tmp_path = NONCE_PATH.with_suffix(".json.tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, sort_keys=True)
        f.write("\n")
    tmp_path.replace(NONCE_PATH)


def save_next_nonce(address: str, nonce: int) -> None:
    save_nonce_state(address, nonce)


def swap(
    in_token: str,
    zero_for_one: bool,
    amount_specified: int,
    sqrt_price_limit_x96: int | None,
) -> str:
    w3 = Web3(Web3.HTTPProvider(settings.dex_rpc_url))
    account = Account.from_key(settings.bsc_private_key)
    executor_address = Web3.to_checksum_address(settings.contract_address)
    nonce = nonce_for_account(account.address)

    executor = w3.eth.contract(
        address=executor_address,
        abi=EXEC_ABI,
    )

    if sqrt_price_limit_x96 is None:
        sqrt_price_limit_x96 = MIN_SQRT_RATIO + 1 if zero_for_one else MAX_SQRT_RATIO - 1
    recipient = settings.dex_recipient or executor_address

    tx = executor.functions.swap(
        Web3.to_checksum_address(settings.pancake_v3_pool_address),
        Web3.to_checksum_address(recipient),
        zero_for_one,
        int(amount_specified),
        int(sqrt_price_limit_x96),
        Web3.to_checksum_address(in_token),
    ).build_transaction(
        {
            "from": account.address,
            "nonce": nonce,
            "gas": settings.dex_gas_limit,
            "gasPrice": settings.dex_gas_price_wei,
            "chainId": settings.chain_id,
        }
    )

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    next_nonce = nonce + 1
    save_next_nonce(account.address, next_nonce)

    return tx_hash.hex()


async def dex_trade(decision: TradeDecision) -> str:
    dex = decision.dextrade
    amount = _amount0_base_units(dex.quantity)
    if dex.direction == "sell":
        in_token = POOL_TOKEN0_ADDRESS
        zero_for_one = True
        amount_specified = amount
    elif dex.direction == "buy":
        in_token = POOL_TOKEN1_ADDRESS
        zero_for_one = False
        amount_specified = -amount
    else:
        raise ValueError(f"unsupported dex direction: {dex.direction}")

    sqrt_price_limit_x96 = _sqrt_price_limit_from_price(dex.acceptable_price)

    async with _nonce_lock:
        tx_hash = await asyncio.to_thread(
            swap,
            in_token=in_token,
            zero_for_one=zero_for_one,
            amount_specified=amount_specified,
            sqrt_price_limit_x96=sqrt_price_limit_x96,
        )
    return tx_hash


def _amount0_base_units(quantity: Decimal) -> int:
    amount = int((quantity * Decimal(10**18)).to_integral_value(rounding=ROUND_FLOOR))
    if amount <= 0:
        raise ValueError(f"dex quantity must be positive: {quantity}")
    return amount


def _sqrt_price_limit_from_price(price: Decimal) -> int:
    if price <= 0:
        raise ValueError(f"dex acceptable price must be positive: {price}")

    with localcontext() as ctx:
        ctx.prec = 80
        raw = int((price.sqrt() * Q96).to_integral_value(rounding=ROUND_FLOOR))

    return min(max(raw, MIN_SQRT_RATIO + 1), MAX_SQRT_RATIO - 1)
