from __future__ import annotations

import math


def classic_pivots(high: float, low: float, close: float) -> dict[str, float]:
    """Standard floor pivots from prior session H/L/C."""
    if high <= 0 or low <= 0 or close <= 0:
        raise ValueError("Pivot inputs must be positive")
    p = (high + low + close) / 3.0
    r1 = 2.0 * p - low
    s1 = 2.0 * p - high
    r2 = p + (high - low)
    s2 = p - (high - low)
    return {"P": p, "R1": r1, "R2": r2, "S1": s1, "S2": s2}


def near_level(price: float, level: float, tolerance_pct: float) -> bool:
    """True if price is within tolerance_pct of level (relative to level)."""
    if level <= 0 or math.isnan(level) or math.isnan(price):
        return False
    return abs(price - level) / level <= tolerance_pct
