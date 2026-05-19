import asyncio
from typing import Any, Awaitable, Callable

import websockets

from cex_dex_arbitrage.utils.logger import get_logger

log = get_logger(__name__)

OnMessage = Callable[[str], Awaitable[None]]
OnConnect = Callable[[Any], Awaitable[None]]


class WSClient:
    """Reusable WebSocket client with reconnect backoff and optional subscription hook."""

    def __init__(
        self,
        url: str,
        on_message: OnMessage,
        on_connect: OnConnect | None = None,
        name: str = "ws",
        max_backoff: float = 30.0,
    ) -> None:
        self.url = url
        self.on_message = on_message
        self.on_connect = on_connect
        self.name = name
        self.max_backoff = max_backoff

    async def run(self) -> None:
        backoff = 1.0
        while True:
            try:
                async with websockets.connect(self.url) as ws:
                    log.info(f"[{self.name}] connected")
                    backoff = 1.0
                    if self.on_connect is not None:
                        await self.on_connect(ws)
                    async for raw in ws:
                        await self.on_message(raw)
            except Exception as e:
                log.warning(f"[{self.name}] disconnected: {e}; retry in {backoff:.1f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.max_backoff)
