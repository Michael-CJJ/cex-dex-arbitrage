import asyncio

from cex_dex_arbitrage import main as main_module


class _StopGate:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


class _IdleGate:
    def __init__(self) -> None:
        self.idle = asyncio.Event()

    async def wait_idle(self) -> None:
        await self.idle.wait()


async def test_graceful_shutdown_stops_new_work_and_waits_for_drain() -> None:
    arb = _StopGate()
    tick_cache = _StopGate()
    strategy = _StopGate()
    trader = _IdleGate()
    summary = _IdleGate()

    shutdown_task = asyncio.create_task(
        main_module._graceful_shutdown(
            arb=arb,
            tick_cache=tick_cache,
            strategy=strategy,
            trader=trader,
            summary=summary,
            timeout_ms=1_000,
        )
    )
    await asyncio.sleep(0)

    assert arb.stopped is True
    assert tick_cache.stopped is True
    assert strategy.stopped is True
    assert not shutdown_task.done()

    trader.idle.set()
    await asyncio.sleep(0)
    assert not shutdown_task.done()

    summary.idle.set()
    await shutdown_task


async def test_graceful_shutdown_returns_after_timeout() -> None:
    arb = _StopGate()
    tick_cache = _StopGate()
    strategy = _StopGate()
    trader = _IdleGate()
    summary = _IdleGate()

    await main_module._graceful_shutdown(
        arb=arb,
        tick_cache=tick_cache,
        strategy=strategy,
        trader=trader,
        summary=summary,
        timeout_ms=1,
    )

    assert arb.stopped is True
    assert tick_cache.stopped is True
    assert strategy.stopped is True
