"""Cup-and-handle breakout with volume: Bulkowski pattern + volume surge."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "cup_handle_breakout"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float], volumes: list[float]
) -> List[Signal]:
    """Core logic: cup depth 12-45%, handle 2-12%, breakout above cup high with volume."""
    if len(closes) < 75 or len(highs) < 75 or len(volumes) < 10:
        return []
    cup_high = max(highs[-70:-10])
    cup_low = min(closes[-60:-10])
    depth = (cup_high - cup_low) / cup_high if cup_high > 0 else 0
    handle_low = min(closes[-10:])
    handle_pull = (cup_high - handle_low) / cup_high if cup_high > 0 else 0
    breakout = closes[-1] > cup_high
    avg_vol = mean(volumes[-10:-1]) if len(volumes) >= 10 else 1
    vol_surge = volumes[-1] > avg_vol * 1.3
    if 0.12 <= depth <= 0.45 and 0.02 <= handle_pull <= 0.12 and breakout and vol_surge:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.85,
            size_hint=0.85,
            reason=f"Cup+handle: depth={depth:.2%}, handle={handle_pull:.2%}, breakout with vol",
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
        volumes = [float(b.get("v", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, highs, volumes))
    return out


def generate_signal(
    symbol: str, closes: list[float], highs: list[float] = None,
    volumes: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not highs or not volumes:
        return None
    sigs = _v1_signals(symbol, closes, highs, volumes)
    return sigs[0] if sigs else None
