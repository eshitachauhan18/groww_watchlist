from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Optional

from ..models import Quote
from .base import MarketDataProvider, ProviderError, RawQuote

CACHE_TTL_SECONDS = 20
STALE_AFTER_SECONDS = 120
FAILURE_THRESHOLD = 3
CIRCUIT_COOLDOWN_SECONDS = 60
HISTORY_LENGTH = 40


@dataclass
class _CacheEntry:
    quote: RawQuote
    fetched_at: float
    source: str


class _CircuitBreaker:
    """Trips after consecutive provider failures so we stop hammering a
    provider that is already down/rate-limited, and recovers automatically
    after a cooldown instead of needing a manual reset."""

    def __init__(self, threshold: int, cooldown: float):
        self.threshold = threshold
        self.cooldown = cooldown
        self._failures = 0
        self._opened_at: Optional[float] = None

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        self._failures += 1
        if self._failures >= self.threshold and self._opened_at is None:
            self._opened_at = time.time()

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False

        if time.time() - self._opened_at >= self.cooldown:
            # half-open: allow one more real attempt to see if it recovered
            self._opened_at = None
            self._failures = self.threshold - 1
            return False

        return True


class ResilientMarketDataService:
    """Single point of access for quotes. Wraps a primary provider with a
    shared TTL cache + circuit breaker, and falls back to a secondary
    provider (simulated data) rather than surfacing errors to users.

    The cache is shared across every device/watchlist, so 1 user or 1000
    users watching the same symbol still costs one upstream call per TTL
    window - this is what lets the system scale with more users without
    scaling external API usage 1:1.
    """

    def __init__(self, primary: MarketDataProvider, fallback: MarketDataProvider):
        self._primary = primary
        self._fallback = fallback
        self._breaker = _CircuitBreaker(FAILURE_THRESHOLD, CIRCUIT_COOLDOWN_SECONDS)
        self._cache: dict[str, _CacheEntry] = {}
        self._history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=HISTORY_LENGTH))
        self._lock = threading.Lock()

    def refresh(self, symbol: str) -> None:
        """Force-refresh one symbol; used by the background poller so user
        requests almost always hit a warm cache instead of waiting on I/O."""
        self._fetch(symbol)

    def get_quote(self, symbol: str) -> Quote:
        with self._lock:
            entry = self._cache.get(symbol)
            now = time.time()
            if entry is not None and now - entry.fetched_at < CACHE_TTL_SECONDS:
                return self._to_quote(entry, now)
        return self._fetch(symbol)

    def _fetch(self, symbol: str) -> Quote:
        now = time.time()
        if not self._breaker.is_open():
            try:
                raw = self._primary.get_quote(symbol)
                self._breaker.record_success()
                entry = _CacheEntry(raw, now, self._primary.name)
                with self._lock:
                    self._cache[symbol] = entry
                    self._history[symbol].append(raw.price)
                return self._to_quote(entry, now)
            except ProviderError:
                self._breaker.record_failure()

        # primary unavailable (or circuit open): prefer a still-usable
        # last-known-good value over synthetic data, clearly marked stale.
        with self._lock:
            stale_entry = self._cache.get(symbol)
            if stale_entry is not None and now - stale_entry.fetched_at < STALE_AFTER_SECONDS:
                return self._to_quote(stale_entry, now, force_stale=True)

        raw = self._fallback.get_quote(symbol)
        entry = _CacheEntry(raw, now, self._fallback.name)
        with self._lock:
            self._cache[symbol] = entry
            self._history[symbol].append(raw.price)
        return self._to_quote(entry, now)

    def get_history(self, symbol: str) -> list[float]:
        with self._lock:
            return list(self._history.get(symbol, []))

    @staticmethod
    def _currency_for(symbol: str) -> str:
        # Yahoo Finance (and this project) identify NSE/BSE-listed Indian
        # tickers by suffix (e.g. "RELIANCE.NS", "TCS.BO") - same symbol
        # namespace, no separate provider needed for a second market.
        return "INR" if symbol.endswith((".NS", ".BO")) else "USD"

    def _to_quote(self, entry: _CacheEntry, now: float, force_stale: bool = False) -> Quote:
        raw = entry.quote
        pct_change = ((raw.price - raw.prev_close) / raw.prev_close * 100) if raw.prev_close else 0.0
        if force_stale:
            source, stale = "cached", True
        elif entry.source == "simulated":
            source, stale = "simulated", True
        else:
            source, stale = "live", False

        return Quote(
            symbol=raw.symbol,
            price=raw.price,
            prev_close=raw.prev_close,
            volume=raw.volume,
            avg_volume=raw.avg_volume,
            pct_change=round(pct_change, 3),
            as_of=entry.fetched_at,
            source=source,  # type: ignore[arg-type]
            stale=stale,
            currency=self._currency_for(raw.symbol),  # type: ignore[arg-type]
            history=list(self._history.get(raw.symbol, [])),
            day_low=raw.day_low,
            day_high=raw.day_high,
            year_low=raw.year_low,
            year_high=raw.year_high,
            fifty_day_avg=raw.fifty_day_avg,
            two_hundred_day_avg=raw.two_hundred_day_avg,
        )