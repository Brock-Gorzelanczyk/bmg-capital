"""Turtle System 2: 55-day Donchian breakout, exit on 20-day low."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "turtle_donchian_s2"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: buy 55d high breakout, sell 20d low breakdown."""
    if len(closes) < 56 or len(highs) < 56 or len(lows) < 21:
        return []
    high_55 = max(highs[-56:-1])
    low_20 = min(lows[-21:-1])
    if closes[-1] > high_55:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.70,
            size_hint=0.70,
            reason=f"Turtle S2: close {closes[-1]:.2f} > 55d high {high_55:.2f}",
            strategy=STRATEGY_NAME,
        )]
    if closes[-1] < low_20:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.70,
            size_hint=0.70,
            reason=f"Turtle S2 exit: close {closes[-1]:.2f} < 20d low {low_20:.2f}",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        highs = [float(b.get("h", 0)) for b in bar_list]
        lows = [float(b.get("l", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, highs, lows))
    return out


def generate_signal(
    symbol: str, closes: list[float], highs: list[float] = None,
    lows: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not highs or not lows:
        return None
    sigs = _v1_signals(symbol, closes, highs, lows)
    return sigs[0] if sigs else None
