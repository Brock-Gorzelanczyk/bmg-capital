"""Inverse head-and-shoulders reversal: bullish pattern at market lows."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "inverse_hs_reversal"


def _v1_signals(
    symbol: str, closes: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: head lower than shoulders, right shoulder recovering, neckline break."""
    if len(closes) < 30 or len(lows) < 30:
        return []
    left_shoulder = min(lows[-30:-20])
    head = min(lows[-20:-10])
    right_shoulder = min(lows[-10:])
    neckline = max(closes[-30:])
    if (head < left_shoulder and right_shoulder > head * 1.02
            and closes[-1] > neckline * 0.98):
        return [Signal(
            symbol=symbol, side="buy", confidence=0.70,
            size_hint=0.70,
            reason=(
                f"Inverse H&S: head={head:.2f} < ls={left_shoulder:.2f}, "
                f"rs={right_shoulder:.2f}, neckline={neckline:.2f}"
            ),
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        lows = [float(b.get("l", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, lows))
    return out


def generate_signal(
    symbol: str, closes: list[float], lows: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not lows:
        return None
    sigs = _v1_signals(symbol, closes, lows)
    return sigs[0] if sigs else None
