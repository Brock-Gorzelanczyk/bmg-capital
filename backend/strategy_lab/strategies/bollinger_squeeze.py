"""Bollinger Squeeze strategy — volatility contraction breakout."""
from __future__ import annotations

import logging
from statistics import mean, stdev
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "bollinger_squeeze"
PERIOD = 20
MULT = 2.0
LOOKBACK = 130


def _bandwidth(closes: list[float], period: int = PERIOD, mult: float = MULT) -> float:
    """Compute Bollinger Band width for a window."""
    if len(closes) < period:
        return float("inf")
    window = closes[-period:]
    mid = mean(window)
    if mid == 0:
        return float("inf")
    sd = stdev(window) if len(window) > 1 else 0.0
    upper = mid + mult * sd
    lower = mid - mult * sd
    return (upper - lower) / mid


def _v1_signals(
    symbol: str,
    closes: list[float],
    period: int = PERIOD,
    mult: float = MULT,
) -> List[Signal]:
    """Return buy signal on BB squeeze breakout.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 130.
    """
    if len(closes) < LOOKBACK:
        return []

    current_bw = _bandwidth(closes, period, mult)

    # Compute historical bandwidths over the lookback window (sample every 5 bars)
    hist_bws = []
    for offset in range(PERIOD, LOOKBACK - period, 5):
        slice_end = len(closes) - offset
        hist_bws.append(_bandwidth(closes[:slice_end], period, mult))

    if not hist_bws:
        return []

    hist_bws_sorted = sorted(hist_bws)
    percentile_10 = hist_bws_sorted[max(0, len(hist_bws_sorted) // 10)]

    # BB for current bar
    window = closes[-period:]
    mid = mean(window)
    sd = stdev(window) if len(window) > 1 else 0.0
    upper = mid + mult * sd

    squeeze = current_bw <= percentile_10
    breakout = closes[-1] > upper

    if squeeze and breakout:
        confidence = max(0.5, min(0.9, 1 - current_bw * 10))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"BB squeeze breakout: bw {current_bw:.4f} at 10th-pct low; "
                f"close {closes[-1]:.2f} > upper {upper:.2f}"
            ),
            strategy=STRATEGY_NAME,
        )]

    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py."""
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes))
    return out


def generate_signal(symbol: str, closes: list[float]) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes)
    return signals[0] if signals else None
