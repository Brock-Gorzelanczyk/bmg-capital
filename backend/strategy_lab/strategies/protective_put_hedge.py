"""Protective put hedge: buy OTM put when portfolio extended or VIX complacent."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "protective_put_hedge"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: near 20d high = good time to hedge with protective put."""
    if len(closes) < 20:
        return []
    high_20 = max(closes[-20:])
    extended = closes[-1] > high_20 * 0.97
    if extended:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.55,
            size_hint=0.55,
            reason="Protective put: buy 60-90d 5-10% OTM put as tail hedge while extended",
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
