from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


class ProviderError(Exception):
    """Raised when a market data provider cannot return a quote right now."""


class ProviderUnavailable(ProviderError):
    """Provider could not be reached or answered ambiguously (network error,
    rate limit, timeout). We do NOT know if the symbol is valid - callers
    should fail open (assume valid) rather than reject the user's input."""


class SymbolNotFound(ProviderError):
    """Provider was reached successfully and affirmatively reported that the
    symbol does not exist. Safe to reject the user's input."""


@dataclass
class RawQuote:
    symbol: str
    price: float
    prev_close: float
    volume: float
    avg_volume: float
    day_low: Optional[float] = None
    day_high: Optional[float] = None
    year_low: Optional[float] = None
    year_high: Optional[float] = None
    fifty_day_avg: Optional[float] = None
    two_hundred_day_avg: Optional[float] = None


class MarketDataProvider(ABC):
    """A source of quotes. Implementations must fail fast (raise ProviderError)
    rather than hang, so the resilient aggregator can fall back quickly."""

    name: str

    @abstractmethod
    def get_quote(self, symbol: str) -> RawQuote: ...