"""Camarilla pivot reversion: intraday mean reversion to H3/L3 levels."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "camarilla_pivot_reversion"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: revert to H3/L3 Camarilla pivot levels from prior day."""
    if len(closes) < 2 or len(highs) < 2 or len(lows) < 2:
        return []
    prev_high = highs[-2]
    prev_low = lows[-2]
    prev_close = closes[-2]
    rng = prev_high - prev_low
    h3 = prev_close + rng * 1.1 / 4
    l3 = prev_close - rng * 1.1 / 4
    if closes[-1] < l3:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.62,
            size_hint=0.62,
            reason=f"Camarilla L3 reversion buy: {closes[-1]:.2f} < L3={l3:.2f}",
            strategy=STRATEGY_NAME,
        )]
    if closes[-1] > h3:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.62,
            size_hint=0.62,
            reason=f"Camarilla H3 reversion sell: {closes[-1]:.2f} > H3={h3:.2f}",
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
