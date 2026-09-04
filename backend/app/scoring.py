"""Attention scoring: turns a raw quote into 'how much does this deserve the
user's attention right now', instead of leaving them to eyeball raw % change.

score = volatility-adjusted move size (z-score vs the symbol's own typical
daily swing) blended with a volume-surge signal (unusual volume often
precedes/confirms a real move, not noise). Both are normalized so a 1% move
in a normally-sleepy stock ranks higher than a 1% move in a stock that swings
5% every day - "meaningful" is relative to the symbol, not an absolute cutoff.

"What counts as meaningful" is also deliberately left partly up to the user:
`sensitivity` scales the volatility divisor (conservative = harder to
trigger, only the biggest moves count; aggressive = easier to trigger, more
gets flagged) rather than us picking one fixed answer for everyone.
"""

from __future__ import annotations

import statistics
from typing import Optional

from .models import Quote, ScoreBreakdown

# Fallback typical daily volatility (%) used until a symbol has built up
# enough of its own price history (see estimate_volatility_pct below).
DEFAULT_VOLATILITY_PCT = 1.5
MIN_HISTORY_FOR_VOLATILITY = 5

SENSITIVITY_MULTIPLIERS = {"conservative": 1.6, "balanced": 1.0, "aggressive": 0.6}
DEFAULT_SENSITIVITY = "balanced"

HIGH_THRESHOLD = 2.5
MEDIUM_THRESHOLD = 1.2


def estimate_volatility_pct(history: list[float]) -> Optional[float]:
    """Realized volatility from the symbol's own recent price history (stdev
    of period-over-period % changes) - so 'typical swing' reflects this
    stock's actual recent behavior instead of a single guessed constant for
    every symbol. Returns None until there's enough history to be meaningful,
    so callers can fall back to the constant early on."""
    if len(history) < MIN_HISTORY_FOR_VOLATILITY:
        return None
    pct_changes = [(b - a) / a * 100 for a, b in zip(history, history[1:]) if a]
    if len(pct_changes) < MIN_HISTORY_FOR_VOLATILITY - 1:
        return None
    return statistics.pstdev(pct_changes)


def compute_score(
    quote: Quote,
    typical_volatility_pct: float = DEFAULT_VOLATILITY_PCT,
    sensitivity: str = DEFAULT_SENSITIVITY,
) -> tuple[float, str, ScoreBreakdown]:
    realized_volatility = estimate_volatility_pct(quote.history)
    base_volatility = realized_volatility if realized_volatility is not None else typical_volatility_pct
    multiplier = SENSITIVITY_MULTIPLIERS.get(sensitivity, 1.0)
    volatility = max(base_volatility * multiplier, 0.25)  # avoid divide-by-near-zero blowups

    move_z = abs(quote.pct_change) / volatility

    volume_ratio = (quote.volume / quote.avg_volume) if quote.avg_volume else 1.0
    volume_signal = min(max(volume_ratio - 1, 0), 4) / 4  # 0..1, saturates at 5x avg volume

    move_contribution = round(move_z * 0.75, 3)
    volume_contribution = round(volume_signal * 0.25, 3)
    score = round(move_contribution + volume_contribution, 3)
    breakdown = ScoreBreakdown(move_contribution=move_contribution, volume_contribution=volume_contribution)

    if score >= HIGH_THRESHOLD:
        level = "high"
    elif score >= MEDIUM_THRESHOLD:
        level = "medium"
    else:
        level = "low"
    return score, level, breakdown