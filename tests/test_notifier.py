import base64
import hashlib
import hmac
import json
import urllib.parse
from decimal import Decimal

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.components import notifier as notifier_module
from cex_dex_arbitrage.components.notifier import Notifier, _format_summary, _signed_url, send_alert
from cex_dex_arbitrage.models.final import FinalTradeSummary


def _summary() -> FinalTradeSummary:
    return FinalTradeSummary(
        signal_activate_time="2026-05-13 12:00:00.001",
        bps=Decimal("12.34"),
        direction="c-d",
        quantity=Decimal("10"),
        cex_expected_price=Decimal("100.0000"),
        cex_price=Decimal("100.1000"),
        cex_fee=Decimal("0.5005"),
        cex_receive_time="2026-05-13 12:00:00.010",
        dex_expected_price=Decimal("101.0000"),
        dex_price=Decimal("100.9000"),
        dex_gas_usd=Decimal("0.0600"),
        dex_receive_time="2026-05-13 12:00:00.020",
        realized_bps=Decimal("79.92007992007992007992007992"),
        total_fee=Decimal("0.5605"),
    )


def test_signed_url_matches_webhook_signature() -> None:
    webhook = "https://example.test/robot?token=abc"
    secret = "secret-value"
    timestamp = "1778659200000"
    expected_code = hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}\n{secret}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    expected_sign = urllib.parse.quote_plus(base64.b64encode(expected_code).decode("utf-8"))

    assert _signed_url(webhook=webhook, secret=secret, timestamp=timestamp) == (
        f"{webhook}&timestamp={timestamp}&sign={expected_sign}"
    )


def test_format_summary_uses_final_field_order() -> None:
    assert _format_summary(_summary()).splitlines() == [
        "signal_activate_time: 2026-05-13 12:00:00.001",
        "bps: 12.34",
        "direction: c-d",
        "quantity: 10",
        "cex_expected_price: 100.0000",
        "cex_price: 100.1000",
        "cex_fee: 0.5005",
        "cex_receive_time: 2026-05-13 12:00:00.010",
        "dex_expected_price: 101.0000",
        "dex_price: 100.9000",
        "dex_gas_usd: 0.0600",
        "dex_receive_time: 2026-05-13 12:00:00.020",
        "realized_bps: 79.92007992007992007992007992",
        "total_fee: 0.5605",
    ]


async def test_send_alert_posts_signed_text_payload(monkeypatch) -> None:
    posts = []

    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def text(self) -> str:
            return "ok"

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url, data, headers):
            posts.append((url, json.loads(data), headers))
            return FakeResponse()

    monkeypatch.setattr(notifier_module.time, "time", lambda: 1778659200.0)
    monkeypatch.setattr(notifier_module.aiohttp, "ClientSession", FakeSession)

    await send_alert("hello", webhook="https://example.test/robot?token=abc", secret="secret-value")

    assert len(posts) == 1
    url, payload, headers = posts[0]
    assert "timestamp=1778659200000" in url
    assert "sign=" in url
    assert payload == {"msgtype": "text", "text": {"content": "hello"}}
    assert headers == {"Content-Type": "application/json"}


async def test_notifier_sends_formatted_summary(monkeypatch) -> None:
    sent = []

    async def fake_send_alert(txt: str, *, webhook: str, secret: str) -> None:
        sent.append((txt, webhook, secret))

    monkeypatch.setattr(notifier_module, "send_alert", fake_send_alert)
    final_bus: Bus[FinalTradeSummary] = Bus("final-test")
    Notifier(final_bus=final_bus, webhook="webhook", secret="secret").start()

    await final_bus.publish(_summary())

    assert sent == [(_format_summary(_summary()), "webhook", "secret")]
