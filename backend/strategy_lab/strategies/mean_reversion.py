"""Mean Reversion strategy.

Buy when price is 2+ std devs below 20-period SMA (z_score < -2.0).
Sell when z-score crosses back above 1.5.
Confidence: 1 - abs(z_score - threshold) / 5, clamped 0.3-0.9.
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "mean_reversion"
PERIOD = 20
# 2026-07-13 fire-more: stock_swing produced 0 signals from this strategy
# at z-score < -2.0 (that's the 2.5% tail — very rare). Relaxed to -1.2
# (12% of distribution) so we get ~5× more signals. Confidence still
# scales with |z_score| so shallow mean-reversions score low.
BUY_THRESHOLD = -1.2
SELL_THRESHOLD = 1.0


def _sma(prices: list[float], period: int) -> float:
    window = prices[-period:]
    return sum(window) / len(window)


def _std(prices: list[float], period: int) -> float:
    window = prices[-period:]
    mean = sum(window) / len(window)
    variance = sum((p - mean) ** 2 for p in window) / len(window)
    return math.sqrt(variance)


def _v1_signals(symbol: str, closes: list[float], period: int = PERIOD) -> List[Signal]:
    """Return Signals for a close-price series.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last.
        period: Rolling window for SMA/std-dev.
    """
    if len(closes) < period:
        return []

    sma = _sma(closes, period)
    std = _std(closes, period)
    if std == 0:
        return []

    current = closes[-1]
    z_score = (current - sma) / std

    if z_score < BUY_THRESHOLD:
        raw_conf = 1 - abs(z_score - BUY_THRESHOLD) / 5
        confidence = max(0.3, min(0.9, raw_conf))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Mean reversion buy: z_score={z_score:.2f} < {BUY_THRESHOLD} "
                f"(sma={sma:.2f}, std={std:.2f})"
            ),
            strategy=STRATEGY_NAME,
        )]

    if z_score > SELL_THRESHOLD:
        raw_conf = 1 - abs(z_score - SELL_THRESHOLD) / 5
        confidence = max(0.3, min(0.9, raw_conf))
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Mean reversion sell: z_score={z_score:.2f} > {SELL_THRESHOLD} "
                f"(sma={sma:.2f}, std={std:.2f})"
            ),
            strategy=STRATEGY_NAME,
        )]

    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py. Wraps v1 logic over all symbols in bars."""
    out: List[Signal] = []
    period = profile_config.get("mean_reversion_period", PERIOD)
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, period))
    return out


# Backwards-compat shim for code that calls generate_signal() directly
def generate_signal(
    symbol: str,
    current_price: float,
    rolling_mean: float,
    std_dev: float,
    z_score_threshold: float = 2.0,
) -> Optional[Signal]:
    """Single-value convenience wrapper (kept for backwards compatibility)."""
    if std_dev <= 0:
        return None
    z_score = (current_price - rolling_mean) / std_dev
    signals = generate_signals.__wrapped__ if hasattr(generate_signals, "__wrapped__") else None
    # Re-implement inline so we don't need a full history array
    if z_score < BUY_THRESHOLD:
        raw_conf = 1 - abs(z_score - BUY_THRESHOLD) / 5
        confidence = max(0.3, min(0.9, raw_conf))
        return Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"Z-score {z_score:.2f} < {BUY_THRESHOLD} — mean reversion entry",
            strategy=STRATEGY_NAME,
        )
    if z_score > SELL_THRESHOLD:
        raw_conf = 1 - abs(z_score - SELL_THRESHOLD) / 5
        confidence = max(0.3, min(0.9, raw_conf))
        return Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=f"Z-score {z_score:.2f} > {SELL_THRESHOLD} — mean reversion exit",
            strategy=STRATEGY_NAME,
        )
    return None
