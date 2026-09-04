from __future__ import annotations

import asyncio
import logging

from . import db

logger = logging.getLogger("watchlist.poller")

REFRESH_INTERVAL_SECONDS = 20


async def run_poller(service) -> None:
    """Keeps the shared quote cache warm in the background so user requests
    read from cache instead of triggering a synchronous upstream fetch each
    time - this is what keeps request latency flat as the number of watched
    symbols / concurrent users grows."""
    while True:
        symbols = db.all_distinct_symbols()
        for symbol in symbols:
            try:
                # yfinance is blocking I/O; run off the event loop thread.
                await asyncio.to_thread(service.refresh, symbol)
            except Exception:
                logger.exception("poller failed to refresh %s", symbol)
        await asyncio.sleep(REFRESH_INTERVAL_SECONDS)