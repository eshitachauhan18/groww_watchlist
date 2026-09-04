from __future__ import annotations

import logging
from typing import Optional

from ..models import Quote

logger = logging.getLogger(__name__)


class ResilientMarketDataService:
    """
    Wraps a primary provider with a fallback provider.

    Flow:

        Primary provider
              |
              | success
              v
            Quote

        Primary provider
              |
              | failure
              v
        Fallback provider
              |
              v
            Quote
    """

    def __init__(
        self,
        primary,
        fallback,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

        self._cache: dict[str, Quote] = {}

    def get_quote(self, symbol: str) -> Quote:
        symbol = symbol.strip().upper()

        # -----------------------------------------------------
        # 1. Try primary provider
        # -----------------------------------------------------

        try:
            quote = self.primary.get_quote(symbol)

            if quote is not None:
                self._cache[symbol] = quote
                return quote

        except Exception as exc:
            logger.warning(
                "Primary provider failed for %s: %s",
                symbol,
                exc,
            )

        # -----------------------------------------------------
        # 2. Try fallback provider
        # -----------------------------------------------------

        try:
            quote = self.fallback.get_quote(symbol)

            if quote is not None:
                self._cache[symbol] = quote
                return quote

        except Exception as exc:
            logger.warning(
                "Fallback provider failed for %s: %s",
                symbol,
                exc,
            )

        # -----------------------------------------------------
        # 3. Last-resort cached quote
        # -----------------------------------------------------

        cached = self._cache.get(symbol)

        if cached is not None:
            return cached.model_copy(
                update={
                    "source": "cached",
                    "stale": True,
                }
            )

        # -----------------------------------------------------
        # 4. This should almost never happen because the
        # simulated provider should always return a quote.
        # -----------------------------------------------------

        raise RuntimeError(
            f"No market data available for {symbol}"
        )

    def refresh(self, symbol: str) -> Quote:
        """
        Used by the background poller.

        A refresh is simply another attempt to obtain the latest
        quote through the resilient provider chain.
        """

        return self.get_quote(symbol)