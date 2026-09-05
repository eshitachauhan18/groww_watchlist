from __future__ import annotations

import logging

from .base import MarketDataProvider, ProviderError, ProviderUnavailable, RawQuote, SymbolNotFound

logger = logging.getLogger(__name__)


class YFinanceProvider(MarketDataProvider):
    """Real market data via Yahoo Finance. This is the flakiest link in the
    system (rate limits, network, upstream outages) - callers must always go
    through the ResilientMarketDataService, never call this directly."""

    name = "yfinance"

    def get_quote(self, symbol: str) -> RawQuote:
        try:
            import yfinance as yf
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("yfinance not installed") from exc

        try:
            ticker = yf.Ticker(symbol)
            fast = ticker.fast_info
            price = fast.get("last_price")
            prev_close = fast.get("previous_close")
            volume = fast.get("last_volume") or 0
            avg_volume = fast.get("three_month_average_volume") or volume or 1
            day_low = fast.get("day_low")
            day_high = fast.get("day_high")
            year_low = fast.get("year_low")
            year_high = fast.get("year_high")
            fifty_day_avg = fast.get("fifty_day_average")
            two_hundred_day_avg = fast.get("two_hundred_day_average")
        except Exception as exc:
            # Could be a network error, rate limit, or timeout - we can't tell
            # from a generic exception, so treat it as "unknown" not "invalid".
            raise ProviderUnavailable(f"yfinance unreachable for {symbol}: {exc}") from exc

        if not price or price <= 0:
            # We got a clean response but there's no real price data - Yahoo
            # is affirmatively telling us this symbol doesn't exist/trade.
            raise SymbolNotFound(f"no price data for {symbol}")

        return RawQuote(
            symbol=symbol,
            price=float(price),
            prev_close=float(prev_close) if prev_close else float(price),
            volume=float(volume),
            avg_volume=float(avg_volume) or 1.0,
            day_low=float(day_low) if day_low else None,
            day_high=float(day_high) if day_high else None,
            year_low=float(year_low) if year_low else None,
            year_high=float(year_high) if year_high else None,
            fifty_day_avg=float(fifty_day_avg) if fifty_day_avg else None,
            two_hundred_day_avg=float(two_hundred_day_avg) if two_hundred_day_avg else None,
        )