"""Weinstein stage 2 breakout: price above rising 30w SMA with volume confirmation."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "weinstein_stage2_breakout"


def _v1_signals(
    symbol: str, closes: list[float], volumes: list[float]
) -> List[Signal]:
    """Core logic: Stage 2 = above rising 30w SMA with volume."""
    if len(closes) < 165 or len(volumes) < 21:
        return []
    sma30w = mean(closes[-150:])
    sma30w_prev = mean(closes[-165:-15])
    above_sma = closes[-1] > sma30w
    rising_sma = sma30w > sma30w_prev
    vol_avg = mean(volumes[-21:])
    vol_ok = volumes[-1] > vol_avg * 1.2
    if above_sma and rising_sma and vol_ok:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.80,
            size_hint=0.80,
            reason=f"Weinstein Stage 2: above SMA30w={sma30w:.2f}, rising, vol confirmed",
            strategy=STRATEGY_NAME,
        )]
    if closes[-1] < sma30w and sma30w < sma30w_prev:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.70,
            size_hint=0.70,
            reason=f"Weinstein Stage 4: below falling SMA30w={sma30w:.2f}",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        volumes = [float(b.get("v", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, volumes))
    return out


def generate_signal(
    symbol: str, closes: list[float], volumes: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not volumes:
        return None
    sigs = _v1_signals(symbol, closes, volumes)
    return sigs[0] if sigs else None
