from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

import yfinance as yf

from ..models import Quote

logger = logging.getLogger(__name__)

INDIANAPI_BASE_URL = "https://stock.indianapi.in"

try:
    import requests
except ImportError:
    requests = None

# Fix Windows certificate-chain issues for HTTPS requests.
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass


class YFinanceProvider:
    """
    Primary market-data provider.

    Indian stocks:
        TCS, TCS.NS, INFY, RELIANCE, etc. -> IndianAPI

    US stocks:
        AAPL, MSFT, NVDA, etc. -> Yahoo Finance

    The class name is kept as YFinanceProvider because main.py
    already expects this class.
    """

    def __init__(self) -> None:
        self.indian_api_key = os.getenv("INDIANAPI_KEY", "").strip()

        # Cache of the last successful quote.
        self._cache: dict[str, Quote] = {}

    # ---------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------

    def get_quote(self, symbol: str) -> Optional[Quote]:
        symbol = symbol.strip().upper()

        if not symbol:
            return None

        try:
            # -------------------------------------------------
            # Explicit Indian NSE symbol
            # Example: TCS.NS
            # -------------------------------------------------
            if symbol.endswith(".NS"):
                return self._get_indian_quote(symbol)

            # -------------------------------------------------
            # Bare symbol
            #
            # Try IndianAPI first.
            #
            # This fixes the case where the application sends
            # "TCS" instead of "TCS.NS".
            #
            # If it isn't an Indian stock, fall back to Yahoo.
            # -------------------------------------------------
            indian_quote = self._get_indian_quote(symbol)

            if indian_quote is not None:
                return indian_quote

            # -------------------------------------------------
            # US / other Yahoo Finance symbol
            # Example: AAPL, MSFT, NVDA
            # -------------------------------------------------
            return self._get_yahoo_quote(symbol)

        except Exception as exc:
            logger.warning(
                "Market data failed for %s: %s",
                symbol,
                exc,
            )

            cached = self._cache.get(symbol)

            if cached is not None:
                return cached.model_copy(
                    update={
                        "source": "cached",
                        "stale": True,
                    }
                )

            return None

    # ---------------------------------------------------------
    # IndianAPI
    # ---------------------------------------------------------

    def _get_indian_quote(self, symbol: str) -> Optional[Quote]:
        if requests is None:
            logger.error("requests package is unavailable")
            return None

        if not self.indian_api_key:
            logger.warning(
                "INDIANAPI_KEY is not configured; cannot fetch %s",
                symbol,
            )
            return None

        ticker = symbol.removesuffix(".NS")

        headers = {
            "x-api-key": self.indian_api_key,
            "Accept": "application/json",
        }

        try:
            response = requests.get(
                f"{INDIANAPI_BASE_URL}/stock",
                params={"name": ticker},
                headers=headers,
                timeout=10,
            )

            response.raise_for_status()

            data = response.json()

        except Exception as exc:
            logger.warning(
                "IndianAPI request failed for %s: %s",
                symbol,
                exc,
            )
            return None

        if not isinstance(data, dict):
            logger.warning(
                "Unexpected IndianAPI response for %s",
                symbol,
            )
            return None

        current_price = self._extract_nse_price(data)

        if current_price is None or current_price <= 0:
            logger.warning(
                "No NSE price returned for %s",
                symbol,
            )
            return None

        pct_change = self._number(
            data.get("percentChange")
        )

        if pct_change is None:
            pct_change = 0.0

        # Derive previous close because IndianAPI may only
        # provide percentage change.
        prev_close = self._derive_previous_close(
            current_price,
            pct_change,
        )

        year_high = self._number(
            data.get("yearHigh")
        )

        year_low = self._number(
            data.get("yearLow")
        )

        now = time.time()

        # Keep .NS in the Quote symbol so the rest of the
        # application knows this is an NSE stock.
        quote_symbol = ticker + ".NS"

        quote = Quote(
            symbol=quote_symbol,
            price=current_price,
            prev_close=prev_close,
            volume=0.0,
            avg_volume=0.0,
            pct_change=pct_change,
            as_of=now,
            source="live",
            stale=False,
            currency="INR",
            history=[current_price],
            day_low=None,
            day_high=None,
            year_low=year_low,
            year_high=year_high,
            fifty_day_avg=None,
            two_hundred_day_avg=None,
        )

        # Cache under both forms.
        self._cache[symbol] = quote
        self._cache[quote_symbol] = quote

        return quote

    def _extract_nse_price(
        self,
        data: dict[str, Any],
    ) -> Optional[float]:
        """
        IndianAPI /stock normally returns:

        "currentPrice": {
            "BSE": ...,
            "NSE": ...
        }
        """

        current_price = data.get("currentPrice")

        if isinstance(current_price, dict):
            nse = self._number(
                current_price.get("NSE")
            )

            if nse is not None:
                return nse

            # Defensive alternatives.
            for key in (
                "NSI",
                "nse",
                "NSE_PRICE",
                "nsePrice",
            ):
                value = self._number(
                    current_price.get(key)
                )

                if value is not None:
                    return value

        # Defensive top-level alternatives.
        for key in (
            "nsePrice",
            "nse_price",
            "NSE",
            "price",
            "current_price",
        ):
            value = self._number(
                data.get(key)
            )

            if value is not None:
                return value

        return None

    # ---------------------------------------------------------
    # Yahoo Finance
    # ---------------------------------------------------------

    def _get_yahoo_quote(
        self,
        symbol: str,
    ) -> Optional[Quote]:

        ticker = yf.Ticker(symbol)

        try:
            history = ticker.history(
                period="5d",
                interval="1d",
                auto_adjust=False,
            )
        except Exception as exc:
            logger.warning(
                "Yahoo Finance request failed for %s: %s",
                symbol,
                exc,
            )
            return None

        if history is None or history.empty:
            logger.warning(
                "No market data returned for %s",
                symbol,
            )
            return None

        latest = history.iloc[-1]

        price = self._number(
            latest.get("Close")
        )

        if price is None or price <= 0:
            logger.warning(
                "No price returned for %s",
                symbol,
            )
            return None

        volume = (
            self._number(latest.get("Volume"))
            or 0.0
        )

        # Previous trading day's close.
        prev_close = price

        if len(history) >= 2:
            previous = self._number(
                history.iloc[-2].get("Close")
            )

            if previous is not None and previous > 0:
                prev_close = previous

        pct_change = 0.0

        if prev_close > 0:
            pct_change = (
                (price - prev_close)
                / prev_close
            ) * 100

        history_prices: list[float] = []

        for value in history["Close"].tolist():
            number = self._number(value)

            if number is not None:
                history_prices.append(number)

        day_low = self._number(
            latest.get("Low")
        )

        day_high = self._number(
            latest.get("High")
        )

        year_low = None
        year_high = None

        try:
            info = ticker.fast_info

            year_low = self._number(
                getattr(info, "year_low", None)
            )

            year_high = self._number(
                getattr(info, "year_high", None)
            )

        except Exception:
            pass

        avg_volume = volume

        if len(history) > 1:
            volumes: list[float] = []

            for value in history["Volume"].tolist():
                number = self._number(value)

                if number is not None and number > 0:
                    volumes.append(number)

            if volumes:
                avg_volume = (
                    sum(volumes) / len(volumes)
                )

        now = time.time()

        quote = Quote(
            symbol=symbol,
            price=price,
            prev_close=prev_close,
            volume=volume,
            avg_volume=avg_volume,
            pct_change=pct_change,
            as_of=now,
            source="live",
            stale=False,
            currency="USD",
            history=history_prices,
            day_low=day_low,
            day_high=day_high,
            year_low=year_low,
            year_high=year_high,
            fifty_day_avg=None,
            two_hundred_day_avg=None,
        )

        self._cache[symbol] = quote

        return quote

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @staticmethod
    def _number(
        value: Any,
    ) -> Optional[float]:

        try:
            if value is None:
                return None

            number = float(value)

            # NaN check
            if number != number:
                return None

            return number

        except (TypeError, ValueError):
            return None

    @staticmethod
    def _derive_previous_close(
        price: float,
        pct_change: float,
    ) -> float:
        """
        current = previous * (1 + percentage / 100)

        Therefore:

        previous = current / (1 + percentage / 100)
        """

        denominator = 1 + (
            pct_change / 100
        )

        if denominator <= 0:
            return price

        return price / denominator