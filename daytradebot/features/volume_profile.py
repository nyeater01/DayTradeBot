from __future__ import annotations

import numpy as np
import pandas as pd


def session_volume_profile(
    bars: pd.DataFrame,
    n_bins: int = 50,
    value_area_pct: float = 0.70,
) -> dict[str, float] | None:
    """
    Approximate session volume profile from intraday bars.
    Distributes each bar's volume evenly across price bins touched by [low, high].
    Returns POC, VAH, VAL.
    """
    if bars is None or len(bars) < 2:
        return None
    if n_bins < 10:
        n_bins = 10

    lo = float(bars["low"].min())
    hi = float(bars["high"].max())
    if hi <= lo:
        return None

    edges = np.linspace(lo, hi, n_bins + 1)
    vol_at = np.zeros(n_bins, dtype=float)

    for _, row in bars.iterrows():
        b_lo = float(row["low"])
        b_hi = float(row["high"])
        vol = float(row["volume"])
        if vol <= 0 or b_hi < b_lo:
            continue
        touched = (edges[:-1] < b_hi) & (edges[1:] > b_lo)
        count = int(touched.sum())
        if count <= 0:
            continue
        share = vol / count
        vol_at[touched] += share

    if vol_at.sum() <= 0:
        return None

    poc_idx = int(np.argmax(vol_at))
    poc = float((edges[poc_idx] + edges[poc_idx + 1]) / 2.0)

    target = vol_at.sum() * value_area_pct
    chosen = {poc_idx}
    acc = vol_at[poc_idx]
    lo_i, hi_i = poc_idx, poc_idx
    while acc < target and (lo_i > 0 or hi_i < n_bins - 1):
        down = vol_at[lo_i - 1] if lo_i > 0 else -1.0
        up = vol_at[hi_i + 1] if hi_i < n_bins - 1 else -1.0
        if up >= down:
            hi_i += 1
            chosen.add(hi_i)
            acc += vol_at[hi_i]
        else:
            lo_i -= 1
            chosen.add(lo_i)
            acc += vol_at[lo_i]

    val = float(edges[min(chosen)])
    vah = float(edges[max(chosen) + 1])
    return {"POC": poc, "VAH": vah, "VAL": val, "session_low": lo, "session_high": hi}
