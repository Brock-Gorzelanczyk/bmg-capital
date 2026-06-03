"""Idiosyncratic momentum: stock-specific momentum via position in 60d high-low range."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "idiosyncratic_momentum"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: price position in 60d range as idiosyncratic momentum proxy."""
    if len(closes) < 60 or len(highs) < 60 or len(lows) < 60:
        return []
    range_high = max(highs[-60:])
    range_low = min(lows[-60:])
    denom = range_high - range_low + 0.01
    position_in_range = (closes[-1] - range_low) / denom
    if position_in_range > 0.70:
        conf = min(0.80, position_in_range * 0.8)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Idiosyncratic momentum: 60d range position {position_in_range:.2%}",
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
