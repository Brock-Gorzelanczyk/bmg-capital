"""Darvas Box breakout: consolidation box followed by continuation breakout."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "darvas_box_breakout"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float]
) -> List[Signal]:
    """Core logic: price makes high, consolidates, then breaks out again."""
    if len(closes) < 15 or len(highs) < 15:
        return []
    recent_high = max(highs[-10:-5])
    box_high = max(highs[-5:])
    consolidation = box_high < recent_high * 1.03
    breakout = closes[-1] > box_high and closes[-1] > recent_high
    if consolidation and breakout:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.68,
            size_hint=0.68,
            reason=f"Darvas box breakout: above box_high={box_high:.2f}, prior_high={recent_high:.2f}",
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
