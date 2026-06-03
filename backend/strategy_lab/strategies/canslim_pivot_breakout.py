"""CANSLIM pivot breakout: O'Neil method with volume confirmation."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "canslim_pivot_breakout"


def _v1_signals(
    symbol: str, closes: list[float], highs: list[float], volumes: list[float]
) -> List[Signal]:
    """Core logic: price breaks above 52w high on above-average volume."""
    if len(closes) < 252 or len(highs) < 252 or len(volumes) < 21:
        return []
    prior_high = max(highs[-252:-5])
    breakout = closes[-1] > prior_high
    vol_avg = mean(volumes[-21:])
    vol_confirm = volumes[-1] > vol_avg * 1.4
    if breakout and vol_confirm:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.78,
            size_hint=0.78,
            reason=f"CANSLIM pivot: breakout above {prior_high:.2f}, vol {volumes[-1]:.0f} vs avg {vol_avg:.0f}",
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
        volumes = [float(b.get("v", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, highs, volumes))
    return out


def generate_signal(
    symbol: str, closes: list[float], highs: list[float] = None,
    volumes: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not highs or not volumes:
        return None
    sigs = _v1_signals(symbol, closes, highs, volumes)
    return sigs[0] if sigs else None
