"""Poor Man's Covered Call (diagonal): long LEAPS + short near-term call."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "pmcc_diagonal"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: uptrend + not over-extended = good PMCC setup."""
    if len(closes) < 20:
        return []
    sma20 = mean(closes[-20:])
    in_uptrend = closes[-1] > sma20
    recent_max = max(closes[-20:])
    not_extended = closes[-1] < recent_max * 1.05
    if in_uptrend and not_extended:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.68,
            size_hint=0.68,
            reason="PMCC diagonal: buy 12-18mo LEAPS 70-80 delta, sell 30d OTM call",
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
