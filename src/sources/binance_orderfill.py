import asyncio
import hashlib
import hmac
import json
import time
import uuid
from decimal import Decimal
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

from cex_dex_arbitrage.config import settings
from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.result import CexFill, CexWrong, TradeResult
from cex_dex_arbitrage.utils.logger import get_logger

log = get_logger(__name__)

BINANCE_FUTURES_WS_API_URL = "wss://ws-fapi.binance.com/ws-fapi/v1"
HEARTBEAT_INTERVAL_SECONDS = 30.0
HEARTBEAT_TIMEOUT_SECONDS = 10.0
RECONNECT_BACKOFF_SECONDS = 3.0


class BinanceOrderFillSource:
    def __init__(
        self,
        result_bus: Bus[TradeResult],
        *,
        url: str = BINANCE_FUTURES_WS_API_URL,
        heartbeat_interval: float = HEARTBEAT_INTERVAL_SECONDS,
        heartbeat_timeout: float = HEARTBEAT_TIMEOUT_SECONDS,
        reconnect_backoff: float = RECONNECT_BACKOFF_SECONDS,
    ) -> None:
        self.result_bus = result_bus
        self.url = url
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.reconnect_backoff = reconnect_backoff
        self._running = False
        self._connected = asyncio.Event()
        self._ws: Any | None = None
        self._send_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    async def run(self) -> None:
        self._running = True
        while self._running:
            try:
                async with websockets.connect(self.url, ping_interval=None) as ws:
                    log.info("Binance order fill source connected")
                    self._ws = ws
                    self._connected.set()
                    heartbeat_task = asyncio.create_task(
                        self._heartbeat(ws),
                        name="binance-orderfill-heartbeat",
                    )
                    try:
                        async for raw in ws:
                            await self._handle_message(raw)
                    finally:
                        heartbeat_task.cancel()
                        try:
                            await heartbeat_task
                        except asyncio.CancelledError:
                            pass
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning(f"Binance order fill source disconnected: {exc}")
            finally:
                self._ws = None
                self._connected.clear()

            if self._running:
                await asyncio.sleep(self.reconnect_backoff)

    async def stop(self) -> None:
        self._running = False
        if self._ws is not None:
            await self._ws.close()

    async def _heartbeat(self, ws: Any) -> None:
        while self._running:
            await asyncio.sleep(self.heartbeat_interval)
            try:
                pong_waiter = await ws.ping()
                await asyncio.wait_for(pong_waiter, timeout=self.heartbeat_timeout)
            except (asyncio.TimeoutError, ConnectionClosed) as exc:
                log.warning(f"Binance order fill source heartbeat failed: {exc}")
                await ws.close()
                return

    async def _handle_message(self, raw: str | bytes) -> None:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")

        msg = json.loads(raw)
        status = int(msg.get("status") or 0)
        if status != 200:
            await self.result_bus.publish(_cex_wrong_from_api_error(msg))
            return

        result = _cex_result_from_order_response(msg)
        if result is not None:
            await self.result_bus.publish(result)

    async def send_signed_request(
        self,
        method: str,
        params: dict[str, str | int],
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        await asyncio.wait_for(self._connected.wait(), timeout=timeout)
        if self._ws is None:
            raise RuntimeError("Binance order fill source is not connected")

        request_id = str(uuid.uuid4())
        signed_params = _signed_params(params)
        request = {
            "id": request_id,
            "method": method,
            "params": signed_params,
        }

        async with self._send_lock:
            await self._ws.send(json.dumps(request, separators=(",", ":")))
        return {"id": request_id, "method": method, "status": "SENT"}

    async def place_fok_limit_order(
        self,
        *,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
    ) -> dict[str, Any]:
        return await self.send_signed_request(
            "order.place",
            {
                "apiKey": settings.binance_api_key,
                "symbol": symbol,
                "side": side,
                "type": "LIMIT",
                "timeInForce": "FOK",
                "quantity": _decimal_param(quantity),
                "price": _decimal_param(price),
                "newOrderRespType": "RESULT",
                "timestamp": int(time.time() * 1000),
            },
        )


_orderfill_source: BinanceOrderFillSource | None = None


def set_binance_orderfill_source(source: BinanceOrderFillSource) -> None:
    global _orderfill_source
    _orderfill_source = source


async def place_fok_limit_order(
    *,
    symbol: str,
    side: str,
    quantity: Decimal,
    price: Decimal,
) -> dict[str, Any]:
    if _orderfill_source is None:
        raise RuntimeError("BinanceOrderFillSource is not initialized")
    return await _orderfill_source.place_fok_limit_order(
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
    )


def _cex_result_from_order_response(msg: dict[str, Any]) -> CexFill | CexWrong | None:
    result = msg.get("result")
    if not isinstance(result, dict) or "orderId" not in result:
        return None

    now_ms = time.time_ns() // 1_000_000
    send_time = int(result.get("updateTime") or result.get("time") or now_ms)
    side = str(result.get("side") or "").upper()
    status = str(result.get("status") or "UNKNOWN")
    executed_quantity = _decimal_value(result.get("executedQty"))
    quote_quantity = _decimal_value(result.get("cumQuote"))

    if status == "FILLED" and executed_quantity > 0:
        return CexFill(
            symbol=str(result.get("symbol") or ""),
            order_id=int(result["orderId"]),
            client_order_id=str(result.get("clientOrderId") or ""),
            status=status,
            direction=_direction_from_side(side),
            price=_decimal_value(result.get("avgPrice")),
            quantity=executed_quantity,
            quote_quantity=quote_quantity,
            send_time=send_time,
            receive_time=now_ms,
        )

    return CexWrong(
        symbol=str(result.get("symbol") or ""),
        order_id=_int_or_none(result.get("orderId")),
        client_order_id=str(result.get("clientOrderId") or ""),
        status=status,
        direction=_direction_from_side(side),
        price=_decimal_value(result.get("price") or result.get("avgPrice")),
        quantity=_decimal_value(result.get("origQty") or result.get("quantity")),
        executed_quantity=executed_quantity,
        quote_quantity=quote_quantity,
        reason=_wrong_reason(status, result),
        raw=msg,
        send_time=send_time,
        receive_time=now_ms,
    )


def _cex_wrong_from_api_error(msg: dict[str, Any]) -> CexWrong:
    now_ms = time.time_ns() // 1_000_000
    return CexWrong(
        symbol=None,
        order_id=None,
        client_order_id=None,
        status="API_ERROR",
        direction=None,
        price=None,
        quantity=None,
        executed_quantity=None,
        quote_quantity=None,
        reason=_api_error_reason(msg),
        raw=msg,
        send_time=None,
        receive_time=now_ms,
    )


def _wrong_reason(status: str, result: dict[str, Any]) -> str:
    reject_reason = result.get("rejectReason")
    if reject_reason:
        return str(reject_reason)
    if status == "EXPIRED":
        return "order expired without fill"
    if status == "REJECTED":
        return "order rejected"
    return "order was not fully filled"


def _api_error_reason(msg: dict[str, Any]) -> str:
    error = msg.get("error")
    if isinstance(error, dict):
        code = error.get("code")
        message = error.get("msg") or error.get("message")
        if code is not None and message:
            return f"{code}: {message}"
        if message:
            return str(message)
    return str(msg)


def _decimal_value(value: Any) -> Decimal:
    if value in {None, ""}:
        return Decimal("0")
    return Decimal(str(value))


def _int_or_none(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _direction_from_side(side: str) -> str:
    if side == "BUY":
        return "buy"
    if side == "SELL":
        return "sell"
    return side.lower()


def _signed_params(params: dict[str, str | int]) -> dict[str, str | int]:
    payload = "&".join(f"{key}={params[key]}" for key in sorted(params))
    signature = hmac.new(
        settings.binance_api_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {**params, "signature": signature}


def _decimal_param(value: Decimal) -> str:
    return format(value, "f")
