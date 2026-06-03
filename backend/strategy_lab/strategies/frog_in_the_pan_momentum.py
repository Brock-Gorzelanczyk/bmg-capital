"""Frog-in-the-pan momentum: many small positive days > volatile momentum."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "frog_in_the_pan_momentum"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: many positive days with smooth returns = durable momentum."""
    if len(closes) < 60:
        return []
    returns = [closes[i] / closes[i - 1] - 1 for i in range(-60, 0)]
    pos_days = sum(1 for r in returns if r > 0)
    avg_return = mean(returns)
    if pos_days > 36 and avg_return > 0.001:
        conf = min(0.75, pos_days / 60 * 0.8)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Frog-in-pan: {pos_days}/60 positive days, avg return {avg_return:.4f}",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    """Backwards-compat shim."""
    sigs = _v1_signals(symbol, closes)
    return sigs[0] if sigs else None
