"""Sector momentum rotation: rank sectors by 1-3 month return, long top momentum."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "sector_momentum_rotation"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: blended 1-month and 3-month momentum score."""
    if len(closes) < 63:
        return []
    ret_3m = (closes[-1] - closes[-63]) / closes[-63]
    ret_1m = (closes[-1] - closes[-21]) / closes[-21] if len(closes) >= 21 else ret_3m
    score = ret_3m * 0.7 + ret_1m * 0.3
    if score > 0.04:
        conf = min(0.85, 0.5 + score * 3)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Sector momentum: 3m={ret_3m:.2%}, 1m={ret_1m:.2%}, score={score:.2%}",
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
