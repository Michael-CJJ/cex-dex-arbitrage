import asyncio

from cex_dex_arbitrage.buses.base import Bus
from cex_dex_arbitrage.models.market import BNBPrice, MarketTick, OrderBookTick, SwapTick
from cex_dex_arbitrage.utils.logger import get_logger

log = get_logger(__name__)

DEFAULT_SWAP_QUIET_MS = 2


class TickCache:
    """Filter raw market ticks before they are used for arbitrage calculation."""

    def __init__(
        self,
        market_bus: Bus[MarketTick],
        valid_market_bus: Bus[MarketTick],
        *,
        swap_quiet_ms: int = DEFAULT_SWAP_QUIET_MS,
    ) -> None:
        self.market_bus = market_bus
        self.valid_market_bus = valid_market_bus
        self.swap_quiet_ms = swap_quiet_ms
        self._running = False
        self._latest_swap: SwapTick | None = None
        self._swap_flush_task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    def start(self) -> None:
        self._running = True
        self.market_bus.subscribe(self._on_tick)

    def stop(self) -> None:
        self._running = False
        if self._swap_flush_task is not None:
            self._swap_flush_task.cancel()
            self._swap_flush_task = None
        self._latest_swap = None

    async def _on_tick(self, tick: MarketTick) -> None:
        if not self._running:
            return

        if isinstance(tick, (OrderBookTick, BNBPrice)):
            await self.valid_market_bus.publish(tick)
            return

        if isinstance(tick, SwapTick):
            await self._cache_swap(tick)

    async def _cache_swap(self, tick: SwapTick) -> None:
        async with self._lock:
            self._latest_swap = tick
            if self._swap_flush_task is not None:
                self._swap_flush_task.cancel()
            self._swap_flush_task = asyncio.create_task(self._flush_swap_after_quiet())
            self._swap_flush_task.add_done_callback(_log_background_task_failure)

    async def _flush_swap_after_quiet(self) -> None:
        await asyncio.sleep(self.swap_quiet_ms / 1000)

        async with self._lock:
            if not self._running or self._latest_swap is None:
                return
            tick = self._latest_swap
            self._latest_swap = None
            self._swap_flush_task = None

        await self.valid_market_bus.publish(tick)


def _log_background_task_failure(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        log.exception("tick cache swap flush failed")
