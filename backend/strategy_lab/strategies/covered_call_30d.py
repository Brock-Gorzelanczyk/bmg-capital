"""Covered call (30d): sell OTM call against long stock when range-bound."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "covered_call_30d"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: range-bound last week = favorable for covered call income."""
    if len(closes) < 5:
        return []
    returns_5d = [(closes[i] - closes[i - 1]) / closes[i - 1]
                  for i in range(-5, 0) if closes[i - 1] > 0]
    avg_5d = mean(returns_5d) if returns_5d else 0
    if -0.01 <= avg_5d <= 0.015:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65,
            reason="Covered call: sell 30d 5-7% OTM call for income, stock range-bound",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("vix_regime") == "panic":
        return []
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
