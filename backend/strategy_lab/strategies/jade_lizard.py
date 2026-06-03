"""Jade lizard: sell OTM put + sell OTM call spread. No upside risk when credit > width."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "jade_lizard"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: slightly bullish/neutral setup for jade lizard."""
    if len(closes) < 10:
        return []
    slightly_bullish = closes[-1] > closes[-5] * 0.99 if len(closes) >= 5 else True
    if slightly_bullish:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65,
            reason="Jade lizard: sell OTM put + OTM call spread, credit > spread width = no upside risk",
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
