"""VWAP Reversion strategy.

Buy when price is 1%+ below VWAP, sell when 1%+ above.
VWAP calculated from intraday bars (typical price * volume cumulative).
"""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "vwap_reversion"
DEVIATION_THRESHOLD_PCT = 1.0  # spec: 1%+


def compute_vwap(highs: list[float], lows: list[float], closes: list[float], volumes: list[float]) -> float:
    """Compute VWAP from intraday bars (typical price * volume)."""
    if not highs:
        return 0.0
    cum_tp_vol = 0.0
    cum_vol = 0.0
    for h, l, c, v in zip(highs, lows, closes, volumes):
        tp = (h + l + c) / 3.0
        cum_tp_vol += tp * v
        cum_vol += v
    return cum_tp_vol / cum_vol if cum_vol > 0 else 0.0


def generate_signals(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    deviation_threshold_pct: float = DEVIATION_THRESHOLD_PCT,
) -> List[Signal]:
    """Return VWAP reversion Signals for intraday bar data.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last.
        highs: High prices, most-recent last.
        lows: Low prices, most-recent last.
        volumes: Volume values, most-recent last.
        deviation_threshold_pct: % below/above VWAP required to trigger.
    """
    if len(closes) < 2:
        return []

    vwap = compute_vwap(highs, lows, closes, volumes)
    if vwap <= 0:
        return []

    current = closes[-1]
    deviation_pct = ((current - vwap) / vwap) * 100.0

    if deviation_pct <= -deviation_threshold_pct:
        confidence = max(0.3, min(0.9, abs(deviation_pct) / 5.0))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"VWAP reversion buy: {current:.2f} is {deviation_pct:.2f}% below VWAP {vwap:.2f}",
            strategy=STRATEGY_NAME,
        )]

    if deviation_pct >= deviation_threshold_pct:
        confidence = max(0.3, min(0.9, deviation_pct / 5.0))
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=f"VWAP reversion sell: {current:.2f} is +{deviation_pct:.2f}% above VWAP {vwap:.2f}",
            strategy=STRATEGY_NAME,
        )]

    return []


# Backwards-compat shim
def generate_signal(
    symbol: str,
    current_price: float,
    vwap: float,
    deviation_threshold_pct: float = DEVIATION_THRESHOLD_PCT,
) -> Optional[Signal]:
    """Single-value convenience wrapper (kept for backwards compatibility)."""
    if vwap <= 0:
        return None
    deviation_pct = ((current_price - vwap) / vwap) * 100.0
    if deviation_pct <= -deviation_threshold_pct:
        confidence = max(0.3, min(0.9, abs(deviation_pct) / 5.0))
        return Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"VWAP reversion buy: {current_price:.2f} is {deviation_pct:.2f}% below VWAP {vwap:.2f}",
            strategy=STRATEGY_NAME,
        )
    if deviation_pct >= deviation_threshold_pct:
        confidence = max(0.3, min(0.9, deviation_pct / 5.0))
        return Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=f"VWAP reversion sell: {current_price:.2f} is +{deviation_pct:.2f}% above VWAP {vwap:.2f}",
            strategy=STRATEGY_NAME,
        )
    return None
