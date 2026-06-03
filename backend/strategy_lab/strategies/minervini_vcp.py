"""Minervini VCP: volatility contraction pattern near 52-week high."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "minervini_vcp"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: range contracts 50%+ near highs = VCP setup."""
    if len(closes) < 60 or len(highs) < 60 or len(lows) < 60:
        return []
    range_early = max(highs[-60:-30]) - min(lows[-60:-30])
    range_late = max(highs[-10:]) - min(lows[-10:])
    contraction = range_late < range_early * 0.5 if range_early > 0 else False
    near_high = closes[-1] > max(closes[-60:]) * 0.95
    if contraction and near_high:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.72,
            size_hint=0.72,
            reason=f"Minervini VCP: range contracted {range_late:.2f} from {range_early:.2f}, near high",
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
