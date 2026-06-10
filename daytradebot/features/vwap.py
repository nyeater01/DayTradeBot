from __future__ import annotations

import math

import numpy as np
import pandas as pd


def session_vwap(bars: pd.DataFrame) -> float | None:
    """
    Session VWAP from OHLCV bars (typical price weighted by volume).
    Expects columns: high, low, close, volume.
    """
    if bars is None or bars.empty:
        return None
    vol = bars["volume"].astype(float)
    if vol.sum() <= 0:
        return None
    typical = (bars["high"].astype(float) + bars["low"].astype(float) + bars["close"].astype(float)) / 3.0
    return float((typical * vol).sum() / vol.sum())


def vwap_side(price: float, vwap: float | None) -> str | None:
    if vwap is None or math.isnan(vwap):
        return None
    if price > vwap:
        return "above"
    if price < vwap:
        return "below"
    return "at"
