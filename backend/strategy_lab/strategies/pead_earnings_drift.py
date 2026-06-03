"""PEAD earnings drift: 5-day post-gap drift after earnings volume surge."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "pead_earnings_drift"


def _v1_signals(
    symbol: str, closes: list[float], volumes: list[float], opens: list[float]
) -> List[Signal]:
    """Core logic: gap + volume surge on potential earnings day, drift for 5 days."""
    if len(closes) < 5 or len(volumes) < 5 or len(opens) < 2:
        return []
    gap = (opens[-1] - closes[-2]) / closes[-2] if closes[-2] > 0 else 0
    recent_vols = volumes[-6:-1] if len(volumes) >= 6 else volumes[:-1]
    vol_baseline = mean(recent_vols) + 1 if recent_vols else 1
    vol_surge = volumes[-1] / vol_baseline
    if gap > 0.025 and vol_surge > 1.8:
        conf = min(0.80, gap * 15 + vol_surge * 0.05)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"PEAD: gap={gap:.2%}, vol_surge={vol_surge:.1f}x, hold 5d drift",
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
        opens = [float(b.get("o", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, volumes, opens))
    return out


def generate_signal(
    symbol: str, closes: list[float], volumes: list[float] = None,
    opens: list[float] = None, **kwargs
) -> Optional[Signal]:
    """Backwards-compat shim."""
    if not volumes or not opens:
        return None
    sigs = _v1_signals(symbol, closes, volumes, opens)
    return sigs[0] if sigs else None
