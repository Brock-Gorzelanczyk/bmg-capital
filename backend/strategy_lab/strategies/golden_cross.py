"""Golden Cross strategy — SMA50 crosses above SMA200 for trend entry."""
from __future__ import annotations

import logging
from statistics import mean
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "golden_cross"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Return buy on golden cross, sell on death cross.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 201.
    """
    if len(closes) < 201:
        return []

    sma50 = mean(closes[-50:])
    sma200 = mean(closes[-200:])

    if sma50 == 0 or sma200 == 0:
        return []

    if sma50 > sma200:
        spread = (sma50 - sma200) / sma200
        confidence = min(0.9, max(0.4, spread * 20))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Golden cross: SMA50 {sma50:.2f} > SMA200 {sma200:.2f} "
                f"(spread {spread*100:.2f}%); stop ~-15% below entry"
            ),
            strategy=STRATEGY_NAME,
        )]

    if sma50 < sma200:
        spread = (sma200 - sma50) / sma200
        confidence = min(0.9, max(0.4, spread * 20))
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Death cross: SMA50 {sma50:.2f} < SMA200 {sma200:.2f} "
                f"(spread {spread*100:.2f}%)"
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
