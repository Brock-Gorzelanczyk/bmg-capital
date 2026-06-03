"""Crabel NR7: narrowest range in 7 days signals volatility expansion."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "crabel_nr7_breakout"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float],
    lows: list[float], opens: list[float]
) -> List[Signal]:
    """Core logic: NR7 = today's range is narrowest of last 7 days."""
    if len(closes) < 8 or len(highs) < 8 or len(lows) < 8 or len(opens) < 1:
        return []
    prior_ranges = [highs[i] - lows[i] for i in range(-8, -1)]
    today_range = highs[-1] - lows[-1]
    is_nr7 = today_range <= min(prior_ranges) and today_range < 1.0
    if is_nr7:
        if closes[-1] > opens[-1]:
            return [Signal(
                symbol=symbol, side="buy", confidence=0.63,
                size_hint=0.63,
                reason=f"Crabel NR7: range={today_range:.2f} narrowest of 7d, closed above open",
                strategy=STRATEGY_NAME,
            )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        highs = [float(b.get("h", 0)) for b in bar_list]
        lows = [float(b.get("l", 0)) for b in bar_list]
        opens = [float(b.get("o", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, highs, lows, opens))
    return out


def generate_signal(
    symbol: str, closes: list[float], highs: list[float] = None,
    lows: list[float] = None, opens: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not highs or not lows or not opens:
        return None
    sigs = _v1_signals(symbol, closes, highs, lows, opens)
    return sigs[0] if sigs else None
