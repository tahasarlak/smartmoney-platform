"""Dedicated single-instance Forex stream worker.

Run as a background worker: python -m app.forex_worker
"""
from __future__ import annotations
import asyncio
import logging
import os
import signal
from .forex_intraday import CandleAggregator, run_twelvedata_stream
from .forex_paper import process_forex_tick, record_forex_worker_state

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("tradf.forex_worker")
STOP = asyncio.Event()


async def _handle_tick(aggregator: CandleAggregator, tick: dict) -> None:
    closed = aggregator.update(tick)
    result = process_forex_tick(tick, closed)
    if closed or result["trades_touched"]:
        log.info("FX tick processed symbol=%s closed_candles=%s trades_touched=%s",
                 tick["symbol"], len(closed), result["trades_touched"])


async def main() -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, STOP.set)
        except NotImplementedError:
            pass
    aggregator = CandleAggregator()
    worker_id = os.getenv("TRADF_FOREX_WORKER_ID", "forex-worker")
    record_forex_worker_state(worker_id, status="starting", subscribed_symbols=[])
    async def on_status(state: dict) -> None:
        record_forex_worker_state(
            worker_id, status=state["status"],
            subscribed_symbols=state.get("subscribed_symbols", []),
            last_error=state.get("last_error"),
        )
    await run_twelvedata_stream(
        lambda tick: _handle_tick(aggregator, tick),
        stop_event=STOP, on_status=on_status,
    )


if __name__ == "__main__":
    asyncio.run(main())
