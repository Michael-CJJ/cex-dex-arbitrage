import asyncio
import signal

from cex_dex_arbitrage.config import settings

from cex_dex_arbitrage.buses.market_bus import market_bus
from cex_dex_arbitrage.buses.valid_market_bus import valid_market_bus
from cex_dex_arbitrage.buses.signal_bus import signal_bus
from cex_dex_arbitrage.buses.trade_bus import trade_bus
from cex_dex_arbitrage.buses.result_bus import result_bus
from cex_dex_arbitrage.buses.final_bus import final_bus

from cex_dex_arbitrage.sources.binance_orderbook import BinanceOrderbookSource
from cex_dex_arbitrage.sources.binance_bnb_price import BinanceBNBPriceSource
from cex_dex_arbitrage.sources.pancake_swap_logs import PancakeSwapLogsSource
from cex_dex_arbitrage.sources.binance_orderfill import BinanceOrderFillSource, set_binance_orderfill_source

from cex_dex_arbitrage.components.arb_calculator import ArbCalculator
from cex_dex_arbitrage.components.bnb_price_cache import BNBPriceCache
from cex_dex_arbitrage.components.tick_cache import TickCache
from cex_dex_arbitrage.components.strategy_engine import StrategyEngine
from cex_dex_arbitrage.components.trader import Trader
from cex_dex_arbitrage.components.summary import Summary
from cex_dex_arbitrage.components.recorder import Recorder
from cex_dex_arbitrage.components.notifier import Notifier

from cex_dex_arbitrage.utils.logger import get_logger

log = get_logger(__name__)


async def main() -> None:
    settings.require_live_runtime()

    shutdown_event = asyncio.Event()
    _install_signal_handlers(shutdown_event)

    log.info("initializing runtime components")
    tick_cache = TickCache(market_bus=market_bus, valid_market_bus=valid_market_bus)
    arb = ArbCalculator(market_bus=valid_market_bus, signal_bus=signal_bus)
    bnb_price_cache = BNBPriceCache(market_bus=market_bus)
    strategy = StrategyEngine(signal_bus=signal_bus, trade_bus=trade_bus)
    orderfill_source = BinanceOrderFillSource(result_bus=result_bus)
    set_binance_orderfill_source(orderfill_source)
    summary = Summary(trade_bus=trade_bus, result_bus=result_bus, final_bus=final_bus)
    trader = Trader(trade_bus=trade_bus)
    recorder = Recorder(final_bus=final_bus)
    notifier = Notifier(final_bus=final_bus)

    log.info("starting bus subscribers")
    tick_cache.start()
    arb.start()
    bnb_price_cache.start()
    strategy.start()
    summary.start()
    trader.start()
    recorder.start()
    notifier.start()

    log.info("initializing external sources")
    ob_source = BinanceOrderbookSource(market_bus=market_bus)
    swap_source = PancakeSwapLogsSource(
        market_bus=market_bus,
        result_bus=result_bus,
        bnb_price_cache=bnb_price_cache,
    )
    bnb_source = BinanceBNBPriceSource(market_bus=market_bus)
    source_tasks = [
        asyncio.create_task(ob_source.run(), name="source-binance-orderbook"),
        asyncio.create_task(bnb_source.run(), name="source-binance-bnb"),
        asyncio.create_task(orderfill_source.run(), name="source-binance-orderfill"),
        asyncio.create_task(swap_source.run(), name="source-pancake-swap"),
    ]

    log.info("starting external sources")
    try:
        await _wait_for_shutdown_or_source_exit(shutdown_event, source_tasks)
        await _graceful_shutdown(
            arb=arb,
            tick_cache=tick_cache,
            strategy=strategy,
            trader=trader,
            summary=summary,
            timeout_ms=settings.shutdown_timeout_ms,
        )
    finally:
        await _stop_sources(source_tasks=source_tasks, orderfill_source=orderfill_source)


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def request_shutdown(signame: str) -> None:
        if shutdown_event.is_set():
            return
        log.warning(f"shutdown requested by {signame}")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, request_shutdown, sig.name)
        except (NotImplementedError, RuntimeError, ValueError):
            try:
                signal.signal(
                    sig,
                    lambda _signum, _frame, sig=sig: loop.call_soon_threadsafe(
                        request_shutdown,
                        sig.name,
                    ),
                )
            except (RuntimeError, ValueError):
                pass


async def _wait_for_shutdown_or_source_exit(
    shutdown_event: asyncio.Event,
    source_tasks: list[asyncio.Task[None]],
) -> None:
    shutdown_task = asyncio.create_task(shutdown_event.wait(), name="shutdown-event")
    try:
        done, _ = await asyncio.wait(
            [shutdown_task, *source_tasks],
            return_when=asyncio.FIRST_COMPLETED,
        )
        if shutdown_task in done:
            return

        for task in done:
            if task.cancelled():
                log.warning("runtime source task was cancelled")
                continue
            exc = task.exception()
            if exc is not None:
                raise exc
        log.warning("runtime source stopped unexpectedly")
    finally:
        shutdown_task.cancel()
        await asyncio.gather(shutdown_task, return_exceptions=True)


async def _graceful_shutdown(
    *,
    arb: ArbCalculator,
    tick_cache: TickCache,
    strategy: StrategyEngine,
    trader: Trader,
    summary: Summary,
    timeout_ms: int,
) -> None:
    log.info("graceful shutdown started")
    arb.stop()
    tick_cache.stop()
    strategy.stop()

    try:
        await asyncio.wait_for(
            _drain_runtime(trader=trader, summary=summary),
            timeout=timeout_ms / 1000,
        )
    except asyncio.TimeoutError:
        log.warning("graceful shutdown timed out")
        return

    log.info("graceful shutdown completed")


async def _drain_runtime(*, trader: Trader, summary: Summary) -> None:
    await asyncio.sleep(0)
    await trader.wait_idle()
    await asyncio.sleep(0)
    await summary.wait_idle()


async def _stop_sources(
    *,
    source_tasks: list[asyncio.Task[None]],
    orderfill_source: BinanceOrderFillSource,
) -> None:
    await orderfill_source.stop()
    for task in source_tasks:
        task.cancel()

    results = await asyncio.gather(*source_tasks, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            log.warning(f"source task stopped with error: {type(result).__name__}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.warning("runtime interrupted by user")
    except Exception:
        log.exception("runtime stopped by unhandled exception")
        raise
