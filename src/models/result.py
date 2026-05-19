from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class CexFill:
    symbol: str
    order_id: int
    client_order_id: str
    status: str
    direction: str
    price: Decimal
    quantity: Decimal
    quote_quantity: Decimal
    send_time: int
    receive_time: int


@dataclass(frozen=True)
class CexWrong:
    symbol: str | None
    order_id: int | None
    client_order_id: str | None
    status: str
    direction: str | None
    price: Decimal | None
    quantity: Decimal | None
    executed_quantity: Decimal | None
    quote_quantity: Decimal | None
    reason: str | None
    raw: dict
    send_time: int | None
    receive_time: int


@dataclass(frozen=True)
class DexFill:
    price: Decimal
    quantity: Decimal
    txhash: str
    gas: int
    gas_price_wei: int
    gas_bnb: Decimal
    gas_usd: Decimal | None
    send_time: int
    receive_time: int


TradeResult = CexFill | CexWrong | DexFill
