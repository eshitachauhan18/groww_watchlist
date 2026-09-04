from __future__ import annotations

import hashlib
import math
import time
from typing import Optional

from ..models import Quote


class SimulatedProvider:
    """
    Deterministic fallback provider.

    Used only when the live market-data provider is unavailable.

    The values are deterministic for a symbol, so refreshing the page does
    not create completely random and unrealistic jumps.
    """

    def __init__(self) -> None:
        self._base_prices: dict[str, float] = {}

    def get_quote(self, symbol: str) -> Optional[Quote]:
        symbol = symbol.strip().upper()

        if not symbol:
            return None

        base_price = self._get_base_price(symbol)

        # Use the current time in 20-second buckets.
        # This gives a small movement as the poller refreshes.
        bucket = int(time.time() // 20)

        digest = hashlib.sha256(
            f"{symbol}:{bucket}".encode()
        ).hexdigest()

        raw = int(digest[:8], 16)

        # Deterministic movement between roughly -1.2% and +1.2%.
        movement = ((raw % 2401) - 1200) / 1000

        price = base_price * (1 + movement / 100)

        # Keep the simulated previous close stable around the base price.
        prev_close = base_price

        pct_change = (
            ((price - prev_close) / prev_close) * 100
            if prev_close
            else 0.0
        )

        # Generate a deterministic pseudo-volume.
        volume = 100_000 + (raw % 900_000)
        avg_volume = 500_000

        # Simulated history for the frontend sparkline.
        history = []

        for i in range(8):
            h_digest = hashlib.sha256(
                f"{symbol}:history:{bucket - i}".encode()
            ).hexdigest()

            h_raw = int(h_digest[:8], 16)

            h_move = ((h_raw % 1601) - 800) / 1000

            history.append(
                base_price * (1 + h_move / 100)
            )

        history.reverse()

        currency = "INR" if symbol.endswith(".NS") else "USD"

        return Quote(
            symbol=symbol,
            price=round(price, 2),
            prev_close=round(prev_close, 2),
            volume=float(volume),
            avg_volume=float(avg_volume),
            pct_change=round(pct_change, 3),
            as_of=time.time(),
            source="simulated",
            stale=True,
            currency=currency,
            history=[round(x, 2) for x in history],
            day_low=round(price * 0.985, 2),
            day_high=round(price * 1.015, 2),
            year_low=round(price * 0.70, 2),
            year_high=round(price * 1.30, 2),
            fifty_day_avg=round(base_price, 2),
            two_hundred_day_avg=round(base_price, 2),
        )

    def _get_base_price(self, symbol: str) -> float:
        if symbol in self._base_prices:
            return self._base_prices[symbol]

        # Stable base price generated from the symbol.
        digest = hashlib.sha256(symbol.encode()).hexdigest()
        number = int(digest[:10], 16)

        if symbol.endswith(".NS"):
            # INR-style simulated range.
            base = 100 + (number % 4900)
        else:
            # USD-style simulated range.
            base = 20 + (number % 980)

        self._base_prices[symbol] = float(base)

        return float(base)