"""Ichimoku cloud breakout: price above/below kumo (cloud) for trend direction."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "ichimoku_kumo_breakout"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float], lows: list[float]
) -> List[Signal]:
    """Core logic: tenkan/kijun cross + price vs senkou A cloud."""
    if len(closes) < 27 or len(highs) < 27 or len(lows) < 27:
        return []
    tenkan = (max(highs[-9:]) + min(lows[-9:])) / 2
    kijun = (max(highs[-26:]) + min(lows[-26:])) / 2
    senkou_a = (tenkan + kijun) / 2
    if closes[-1] > senkou_a and tenkan > kijun:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.70,
            size_hint=0.70,
            reason=f"Ichimoku kumo breakout: above cloud, tenkan={tenkan:.2f} > kijun={kijun:.2f}",
            strategy=STRATEGY_NAME,
        )]
    if closes[-1] < senkou_a and tenkan < kijun:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.70,
            size_hint=0.70,
            reason=f"Ichimoku below cloud: tenkan={tenkan:.2f} < kijun={kijun:.2f}",
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
