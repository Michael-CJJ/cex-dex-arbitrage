import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _load_env_file() -> None:
    load_dotenv(PROJECT_ROOT / ".env", override=False)


def _env_str(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    value = _env_str(name)
    if value == "":
        return default
    return int(value)


def _env_float(name: str, default: float) -> float:
    value = _env_str(name)
    if value == "":
        return default
    return float(value)


def _env_decimal(name: str, default: str) -> Decimal:
    value = _env_str(name, default)
    return Decimal(value)


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env_str(name, str(default))
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


@dataclass(frozen=True)
class Settings:
    binance_api_key: str
    binance_api_secret: str
    binance_futures_symbol: str
    cex_quantity_precision: int
    cex_price_precision: int

    chainstack_wss_url: str
    chainstack_https_url: str

    dex_rpc_url: str
    bsc_private_key: str
    contract_address: str
    dex_recipient: str
    dex_gas_limit: int
    dex_gas_price_wei: int
    chain_id: int

    pancake_v3_pool_address: str
    pool_token0_address: str
    pool_token1_address: str
    pool_bnb: bool

    base_bps: float
    threshold_bps: float
    min_signal_interval_ms: int
    max_positions: int
    initial_d_to_c_positions: int
    quantity: Decimal

    webhook: str
    secret: str
    shutdown_timeout_ms: int

    def require_live_runtime(self) -> None:
        required = {
            "BINANCE_API_KEY": self.binance_api_key,
            "BINANCE_API_SECRET": self.binance_api_secret,
            "CHAINSTACK_WSS_URL": self.chainstack_wss_url,
            "CHAINSTACK_HTTPS_URL": self.chainstack_https_url,
            "DEX_RPC_URL": self.dex_rpc_url,
            "BSC_PRIVATE_KEY": self.bsc_private_key,
            "CONTRACT_ADDRESS": self.contract_address,
            "PANCAKE_V3_POOL_ADDRESS": self.pancake_v3_pool_address,
            "POOL_TOKEN0_ADDRESS": self.pool_token0_address,
            "POOL_TOKEN1_ADDRESS": self.pool_token1_address,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"missing live runtime configuration: {joined}")


def load_settings() -> Settings:
    _load_env_file()
    return Settings(
        binance_api_key=_env_str("BINANCE_API_KEY"),
        binance_api_secret=_env_str("BINANCE_API_SECRET"),
        binance_futures_symbol=_env_str("BINANCE_FUTURES_SYMBOL", "BUSDT"),
        cex_quantity_precision=_env_int("CEX_QUANTITY_PRECISION", 0),
        cex_price_precision=_env_int("CEX_PRICE_PRECISION", 4),
        chainstack_wss_url=_env_str("CHAINSTACK_WSS_URL"),
        chainstack_https_url=_env_str("CHAINSTACK_HTTPS_URL"),
        dex_rpc_url=_env_str("DEX_RPC_URL"),
        bsc_private_key=_env_str("BSC_PRIVATE_KEY"),
        contract_address=_env_str("CONTRACT_ADDRESS"),
        dex_recipient=_env_str("DEX_RECIPIENT"),
        dex_gas_limit=_env_int("DEX_GAS_LIMIT", 150000),
        dex_gas_price_wei=_env_int("DEX_GAS_PRICE_WEI", 100000000),
        chain_id=_env_int("CHAIN_ID", 56),
        pancake_v3_pool_address=_env_str("PANCAKE_V3_POOL_ADDRESS"),
        pool_token0_address=_env_str("POOL_TOKEN0_ADDRESS"),
        pool_token1_address=_env_str("POOL_TOKEN1_ADDRESS"),
        pool_bnb=_env_bool("POOL_BNB", False),
        base_bps=_env_float("BASE_BPS", -30.0),
        threshold_bps=_env_float("THRESHOLD_BPS", 10.0),
        min_signal_interval_ms=_env_int("MIN_SIGNAL_INTERVAL_MS", 30000),
        max_positions=_env_int("MAX_POSITIONS", 1),
        initial_d_to_c_positions=_env_int("INITIAL_D_TO_C_POSITIONS", 0),
        quantity=_env_decimal("QUANTITY", "10"),
        webhook=_env_str("WEBHOOK"),
        secret=_env_str("SECRET"),
        shutdown_timeout_ms=_env_int("SHUTDOWN_TIMEOUT_MS", 60000),
    )


settings = load_settings()
