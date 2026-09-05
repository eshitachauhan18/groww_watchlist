from __future__ import annotations

import hashlib
import math
import time

from .base import MarketDataProvider, RawQuote

# Approximate real-world reference prices for common tickers so the simulated
# fallback still looks plausible in a demo (e.g. SIRI shouldn't jump to $400
# just because Yahoo Finance is rate-limited). Unknown symbols fall back to a
# hash-derived price so any ticker still works, just without this realism.
KNOWN_BASE_PRICES: dict[str, float] = {
    # US - high price range
    "BKNG": 4200, "AVGO": 1700, "COST": 900, "NFLX": 700, "MSFT": 420,
    # US - medium price range
    "AAPL": 230, "TSLA": 260, "GOOGL": 175, "AMZN": 190, "NVDA": 140,
    "META": 560, "AMD": 160, "UBER": 75, "DIS": 110, "PYPL": 70, "ROKU": 75,
    # US - low price range
    "SNAP": 11, "PINS": 33, "ETSY": 60, "F": 11, "SIRI": 4, "PLUG": 2.5,
    "NOK": 4, "T": 20, "BAC": 40, "INTC": 22,
    # India (NSE, .NS suffix) - high price range (INR)
    "MRF.NS": 128000, "PAGEIND.NS": 42000, "SHREECEM.NS": 27000,
    "BAJFINANCE.NS": 7200, "MARUTI.NS": 12500, "TCS.NS": 4200,
    # India - medium price range (INR)
    "RELIANCE.NS": 2900, "HINDUNILVR.NS": 2700, "ADANIENT.NS": 2900,
    "KOTAKBANK.NS": 1750, "SUNPHARMA.NS": 1750, "HDFCBANK.NS": 1650,
    "LT.NS": 3600, "INFY.NS": 1900, "AXISBANK.NS": 1150,
    # India - low price range (INR)
    "ICICIBANK.NS": 1250, "TATAMOTORS.NS": 950, "SBIN.NS": 820,
    "WIPRO.NS": 550, "ITC.NS": 470, "NTPC.NS": 370, "COALINDIA.NS": 410,
    "ONGC.NS": 260, "IDEA.NS": 15, "YESBANK.NS": 22,
}


class SimulatedProvider(MarketDataProvider):
    """Deterministic synthetic data used when the real provider is
    unreachable (or for demoing without network). Deterministic per-symbol
    seeding means repeated calls in the same minute give a coherent walk
    instead of pure noise, so the UI still looks plausible while degraded."""

    name = "simulated"

    def _seed(self, symbol: str) -> float:
        digest = hashlib.sha256(symbol.encode()).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    def get_quote(self, symbol: str) -> RawQuote:
        seed = self._seed(symbol)
        if symbol in KNOWN_BASE_PRICES:
            base_price = KNOWN_BASE_PRICES[symbol]
        else:
            base_price = 50 + seed * 950  # spread unknown symbols across a wide price range

        minute_bucket = int(time.time() // 60)
        wobble = math.sin(minute_bucket + seed * 100) * 0.02
        price = base_price * (1 + wobble)
        prev_close = base_price * (1 + math.sin(minute_bucket - 1 + seed * 100) * 0.02)
        avg_volume = 500_000 + seed * 2_000_000
        volume = avg_volume * (0.5 + abs(math.sin(minute_bucket * seed + 1)) * 1.5)
        # 52-week/day ranges and moving averages are synthesized as plausible
        # spreads around the base price - not real history, but consistent
        # and stable per-symbol so the analysis view looks coherent, not random.
        year_high = base_price * (1.15 + seed * 0.2)
        year_low = base_price * (0.65 + seed * 0.15)
        day_high = price * 1.012
        day_low = price * 0.988
        fifty_day_avg = base_price * (0.97 + seed * 0.04)
        two_hundred_day_avg = base_price * (0.92 + seed * 0.08)

        return RawQuote(
            symbol=symbol,
            price=round(price, 2),
            prev_close=round(prev_close, 2),
            volume=round(volume),
            avg_volume=round(avg_volume),
            day_low=round(day_low, 2),
            day_high=round(day_high, 2),
            year_low=round(year_low, 2),
            year_high=round(year_high, 2),
            fifty_day_avg=round(fifty_day_avg, 2),
            two_hundred_day_avg=round(two_hundred_day_avg, 2),
        )