"""Crabel Opening Range Breakout: buy above open+stretch, sell below open-stretch."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "crabel_orb"


def _v1_signals(
    symbol: str, closes: list[float], opens: list[float]
) -> List[Signal]:
    """Core logic: Crabel stretch = mean of last 10 abs(close-open) * 0.1."""
    if len(closes) < 11 or len(opens) < 11:
        return []
    stretch = mean([abs(closes[i] - opens[i]) for i in range(-11, -1)]) * 0.1
    current_open = opens[-1]
    if closes[-1] > current_open + stretch:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.60,
            size_hint=0.60,
            reason=f"Crabel ORB: close {closes[-1]:.2f} > open+stretch {current_open + stretch:.2f}",
            strategy=STRATEGY_NAME,
        )]
    if closes[-1] < current_open - stretch:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.60,
            size_hint=0.60,
            reason=f"Crabel ORB short: close {closes[-1]:.2f} < open-stretch {current_open - stretch:.2f}",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        opens = [float(b.get("o", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, opens))
    return out


def generate_signal(
    symbol: str, closes: list[float], opens: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not opens:
        return None
    sigs = _v1_signals(symbol, closes, opens)
    return sigs[0] if sigs else None
