"""LEAPS stock replacement: buy 12-18mo deep ITM call as capital-efficient stock proxy."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "leaps_stock_replacement"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: consistent uptrend makes LEAPS replacement worthwhile."""
    if len(closes) < 50:
        return []
    sma50 = mean(closes[-50:])
    sma20 = mean(closes[-20:])
    if closes[-1] > sma50 and closes[-1] > sma20:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.70,
            size_hint=0.70,
            reason="LEAPS replacement: 12-18mo 70-80 delta call, ~50% capital vs long stock",
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
