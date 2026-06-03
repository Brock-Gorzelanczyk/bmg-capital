"""Minervini trend template filter: 5-criteria universe filter for stage 2 stocks."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "minervini_trend_template_filter"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float]
) -> List[Signal]:
    """Core logic: 5 Minervini trend template criteria."""
    if len(closes) < 252 or len(highs) < 252:
        return []
    close = closes[-1]
    sma150 = mean(closes[-150:])
    sma200 = mean(closes[-200:])
    sma200_prev = mean(closes[-200:-50])
    low_52w = min(closes[-252:])
    high_52w = max(closes[-252:])
    c1 = close > sma150
    c2 = close > sma200
    c3 = sma150 > sma200_prev
    c4 = close > low_52w * 1.30
    c5 = close >= high_52w * 0.75
    if c1 and c2 and c3 and c4 and c5:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.80,
            size_hint=0.80,
            reason="Minervini trend template: all 5 criteria passed",
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
        out.extend(_v1_signals(symbol, closes, highs))
    return out


def generate_signal(
    symbol: str, closes: list[float], highs: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not highs:
        return None
    sigs = _v1_signals(symbol, closes, highs)
    return sigs[0] if sigs else None
