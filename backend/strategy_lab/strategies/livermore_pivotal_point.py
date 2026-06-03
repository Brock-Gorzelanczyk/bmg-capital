"""Livermore pivotal point: fresh breakout above prior range high after a base."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "livermore_pivotal_point"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float]
) -> List[Signal]:
    """Core logic: first close above prior 40-20 day high (pivotal point)."""
    if len(closes) < 40 or len(highs) < 40:
        return []
    pivot = max(highs[-40:-20])
    if closes[-1] > pivot and closes[-2] <= pivot:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65,
            reason=f"Livermore pivotal point: fresh breakout above pivot {pivot:.2f}",
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
        out.extend(_v1_signals(symbol, closes, highs))
    return out


def generate_signal(
    symbol: str, closes: list[float], highs: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not highs:
        return None
    sigs = _v1_signals(symbol, closes, highs)
    return sigs[0] if sigs else None
