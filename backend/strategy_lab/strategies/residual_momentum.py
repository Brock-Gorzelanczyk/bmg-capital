"""Residual momentum: 6-month return stripped of market beta exposure proxy."""
from __future__ import annotations
import logging
from statistics import mean, stdev
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "residual_momentum"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: high 6m return with low realized vol = strong residual alpha."""
    if len(closes) < 126:
        return []
    raw_6m = (closes[-1] - closes[-126]) / closes[-126]
    if len(closes) > 21:
        daily_rets = [closes[i] / closes[i - 1] - 1 for i in range(-20, 0)]
        vol = stdev(daily_rets) if len(daily_rets) > 1 else 0.02
    else:
        vol = 0.02
    if raw_6m > 0.05 and vol < 0.025:
        conf = min(0.80, raw_6m * 5)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Residual momentum: 6m={raw_6m:.2%} high, vol={vol:.3f} low",
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
