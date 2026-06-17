"""Shared helpers for options strategy modules."""
from __future__ import annotations

import math


def realized_vol_pctile(closes: list[float], window: int = 20) -> float | None:
    """
    Proxy IV Rank using rolling realized vol percentile from price history.

    Returns 0-100 (higher = vol is elevated relative to its own history).
    Returns None if insufficient data.

    This is the key IVR gate for options income strategies: only sell premium
    when realized vol is elevated vs. its own recent history, which tends to
    coincide with elevated implied vol (the edge in short-premium strategies).
    """
    if len(closes) < window + 2:
        return None

    returns = []
    for i in range(1, len(closes)):
        if closes[i - 1] > 0:
            returns.append(math.log(closes[i] / closes[i - 1]))

    if len(returns) < window + 1:
        return None

    windows = [returns[max(0, i - window):i] for i in range(window, len(returns) + 1)]
    rv_series = [
        math.sqrt(252) * math.sqrt(sum(r ** 2 for r in w) / len(w))
        for w in windows
        if w
    ]
    if len(rv_series) < 2:
        return None

    current_rv = rv_series[-1]
    rv_low, rv_high = min(rv_series), max(rv_series)
    if rv_high <= rv_low:
        return None

    return max(0.0, min(100.0, (current_rv - rv_low) / (rv_high - rv_low) * 100.0))


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder-smoothed RSI. Returns None if insufficient data."""
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        delta = closes[i] - closes[i - 1]
        (gains if delta >= 0 else losses).append(abs(delta))
    avg_gain = sum(gains) / period if gains else 0.0
    avg_loss = sum(losses) / period if losses else 0.0
    if avg_loss == 0:
        return 100.0
    return 100.0 - (100.0 / (1.0 + avg_gain / avg_loss))


def sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def range_pct(closes: list[float], lookback: int = 20) -> float | None:
    """(high - low) / midpoint over last N bars as a range-bound proxy."""
    if len(closes) < lookback:
        return None
    window = closes[-lookback:]
    lo, hi = min(window), max(window)
    mid = (lo + hi) / 2
    return (hi - lo) / mid if mid > 0 else None
