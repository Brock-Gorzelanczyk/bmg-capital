"""Cup and Handle pattern recognition strategy."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "cup_and_handle"


def _v1_signals(
    symbol: str,
    closes: list[float],
    highs: list[float],
) -> List[Signal]:
    """Return buy signal on confirmed cup-and-handle breakout.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 75.
        highs: High prices, most-recent last (same length as closes).
    """
    if len(closes) < 75 or len(highs) < 75:
        return []

    cup_high = max(highs[-70:-10])
    cup_low = min(closes[-60:-10])

    if cup_high == 0:
        return []

    cup_depth = (cup_high - cup_low) / cup_high
    handle_low = min(closes[-10:])
    handle_pullback = (cup_high - handle_low) / cup_high
    breakout = closes[-1] > cup_high

    cup_ok = 0.15 <= cup_depth <= 0.40
    handle_ok = 0.03 <= handle_pullback <= 0.08

    if cup_ok and handle_ok and breakout:
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=0.75,
            size_hint=0.75,
            reason=(
                f"Cup & handle breakout: cup_depth {cup_depth*100:.1f}%, "
                f"handle_pullback {handle_pullback*100:.1f}%, "
                f"close {closes[-1]:.2f} > cup_high {cup_high:.2f}"
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
        highs = [float(b.get("h", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, highs))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    highs: list[float],
) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes, highs)
    return signals[0] if signals else None
