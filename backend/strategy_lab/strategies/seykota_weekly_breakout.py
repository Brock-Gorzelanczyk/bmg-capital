"""Seykota weekly breakout: buy 4-week high, sell 2-week low."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "seykota_weekly_breakout"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: 4-week (20d) high breakout, exit on 2-week (10d) low."""
    if len(closes) < 21 or len(highs) < 21 or len(lows) < 11:
        return []
    high_4w = max(highs[-21:-1])
    low_2w = min(lows[-11:-1])
    if closes[-1] > high_4w:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65,
            reason=f"Seykota weekly breakout: {closes[-1]:.2f} > 4w high {high_4w:.2f}",
            strategy=STRATEGY_NAME,
        )]
    if closes[-1] < low_2w:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.65,
            size_hint=0.65,
            reason=f"Seykota weekly exit: {closes[-1]:.2f} < 2w low {low_2w:.2f}",
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
        out.extend(_v1_signals(symbol, closes, highs, lows))
    return out


def generate_signal(
    symbol: str, closes: list[float], highs: list[float] = None,
    lows: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not highs or not lows:
        return None
    sigs = _v1_signals(symbol, closes, highs, lows)
    return sigs[0] if sigs else None
