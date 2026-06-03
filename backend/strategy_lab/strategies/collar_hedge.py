"""Collar hedge: long stock + buy protective put + sell covered call. Cost-neutral hedge."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "collar_hedge"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: collar is always valid as a hedge overlay on existing position."""
    if len(closes) < 5:
        return []
    return [Signal(
        symbol=symbol, side="buy", confidence=0.60,
        size_hint=0.60,
        reason="Collar: buy OTM put + sell OTM call on existing long, near cost-neutral hedge",
        strategy=STRATEGY_NAME,
    )]


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
