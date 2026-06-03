"""Intermediate horizon momentum: months 7-12 window (Novy-Marx 2012)."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "intermediate_horizon_momentum"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: 7-12 month return (months ago 12 to 7) outperforms 2-12m."""
    if len(closes) < 252:
        return []
    ret_7_12 = (closes[-126] - closes[-252]) / closes[-252]
    if ret_7_12 > 0.06:
        conf = min(0.80, 0.5 + ret_7_12 * 3)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Intermediate horizon momentum 7-12m: {ret_7_12:.2%}",
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
