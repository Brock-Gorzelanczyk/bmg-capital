"""Long call directional: buy call option when volume surge + upside momentum."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "long_call_directional"


def _v1_signals(
    symbol: str, closes: list[float], volumes: list[float]
) -> List[Signal]:
    """Core logic: volume surge + 5-day price momentum."""
    if len(closes) < 10:
        return []
    vol_surge = False
    if len(volumes) > 10:
        avg_vol = mean(volumes[-10:-1])
        vol_surge = volumes[-1] > avg_vol * 1.5
    momentum = closes[-1] > closes[-5] if len(closes) >= 5 else False
    if vol_surge and momentum:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.62,
            size_hint=0.62,
            reason="Long call: 30-45d ATM-to-slightly-OTM call, directional vol surge",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if regime.get("vix_regime") == "panic":
        return []
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
    sigs = _v1_signals(symbol, closes, volumes or [])
    return sigs[0] if sigs else None
