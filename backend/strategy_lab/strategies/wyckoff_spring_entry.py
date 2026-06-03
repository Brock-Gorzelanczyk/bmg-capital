"""Wyckoff spring entry: brief shakeout below support followed by quick recovery."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "wyckoff_spring_entry"


def _v1_signals(
    symbol: str, closes: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: intraday dip below support then recovery above it."""
    if len(closes) < 20 or len(lows) < 20:
        return []
    support = min(lows[-20:-5])
    spring = lows[-5] < support * 0.99
    recovery = closes[-1] > support
    if spring and recovery:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.72,
            size_hint=0.72,
            reason=f"Wyckoff spring: dipped to {lows[-5]:.2f} below support {support:.2f}, recovered",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        lows = [float(b.get("l", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, lows))
    return out


def generate_signal(
    symbol: str, closes: list[float], lows: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not lows:
        return None
    sigs = _v1_signals(symbol, closes, lows)
    return sigs[0] if sigs else None
