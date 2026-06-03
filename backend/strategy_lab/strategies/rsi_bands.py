"""RSI Bands strategy.

RSI 14: buy when RSI < 30, sell when RSI > 70.
Confidence: (30 - rsi) / 30 for buy, (rsi - 70) / 30 for sell, clamped 0.3-0.9.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "rsi_bands"
RSI_PERIOD = 14
OVERSOLD = 30.0
OVERBOUGHT = 70.0


def _compute_rsi(closes: list[float], period: int = RSI_PERIOD) -> float:
    """Compute RSI using Wilder's smoothed averages."""
    if len(closes) < period + 1:
        return 50.0  # neutral fallback

    gains, losses = [], []
    for i in range(-period, 0):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains.append(delta)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(delta))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def generate_signals(symbol: str, closes: list[float], period: int = RSI_PERIOD) -> List[Signal]:
    """Return Signals for a close-price series using RSI.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last.
        period: RSI period (default 14).
    """
    if len(closes) < period + 1:
        return []

    rsi = _compute_rsi(closes, period)

    if rsi < OVERSOLD:
        raw_conf = (OVERSOLD - rsi) / OVERSOLD
        confidence = max(0.3, min(0.9, raw_conf))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"RSI {rsi:.1f} < {OVERSOLD} — oversold",
            strategy=STRATEGY_NAME,
        )]

    if rsi > OVERBOUGHT:
        raw_conf = (rsi - OVERBOUGHT) / OVERBOUGHT
        confidence = max(0.3, min(0.9, raw_conf))
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=f"RSI {rsi:.1f} > {OVERBOUGHT} — overbought",
            strategy=STRATEGY_NAME,
        )]

    return []


# Backwards-compat shim
def generate_signal(
    symbol: str,
    rsi: float,
    oversold: float = OVERSOLD,
    overbought: float = OVERBOUGHT,
) -> Optional[Signal]:
    """Single-value convenience wrapper (kept for backwards compatibility)."""
    if rsi < oversold:
        raw_conf = (oversold - rsi) / oversold
        confidence = max(0.3, min(0.9, raw_conf))
        return Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"RSI {rsi:.1f} < {oversold} — oversold",
            strategy=STRATEGY_NAME,
        )
    if rsi > overbought:
        raw_conf = (rsi - overbought) / overbought
        confidence = max(0.3, min(0.9, raw_conf))
        return Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=f"RSI {rsi:.1f} > {overbought} — overbought",
            strategy=STRATEGY_NAME,
        )
    return None
