import base64
import hashlib
import hmac
import json
import time
import urllib.parse
from dataclasses import fields
from typing import Any

import aiohttp

from cex_dex_arbitrage.config import settings
from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.final import FinalTradeSummary
from cex_dex_arbitrage.utils.logger import get_logger

log = get_logger(__name__)


class Notifier:
    """Subscribe to final_bus and send completed two-leg trade notifications."""

    def __init__(
        self,
        final_bus: Bus[FinalTradeSummary],
        *,
        webhook: str | None = None,
        secret: str | None = None,
    ) -> None:
        self.final_bus = final_bus
        self.webhook = settings.webhook if webhook is None else webhook
        self.secret = settings.secret if secret is None else secret

    def start(self) -> None:
        self.final_bus.subscribe(self._on_final)

    async def _on_final(self, summary: FinalTradeSummary) -> None:
        txt = _format_summary(summary)
        await send_alert(txt, webhook=self.webhook, secret=self.secret)


async def send_alert(txt: str, *, webhook: str, secret: str) -> None:
    if not webhook or not secret:
        log.warning("webhook notifier skipped because WEBHOOK or SECRET is empty")
        return

    timestamp = str(round(time.time() * 1000))
    url = _signed_url(webhook=webhook, secret=secret, timestamp=timestamp)
    payload = {
        "msgtype": "text",
        "text": {"content": txt},
    }
    headers = {"Content-Type": "application/json"}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=json.dumps(payload), headers=headers) as response:
            body = await response.text()
            if response.status >= 400:
                log.warning(f"webhook notifier failed: status={response.status}")


def _signed_url(*, webhook: str, secret: str, timestamp: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    hmac_code = hmac.new(
        secret.encode("utf-8"),
        string_to_sign,
        digestmod=hashlib.sha256,
    ).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(hmac_code).decode("utf-8"))
    return f"{webhook}&timestamp={timestamp}&sign={sign}"


def _format_summary(summary: FinalTradeSummary) -> str:
    return "\n".join(
        f"{field.name}: {_format_value(getattr(summary, field.name))}"
        for field in fields(summary)
    )


def _format_value(value: Any) -> str:
    if value is None:
        return "None"
    return str(value)
