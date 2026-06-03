"""Dual momentum GEM: absolute momentum vs T-bill proxy + relative SMA200 filter."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "dual_momentum_gem"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: Antonacci GEM simplified."""
    if len(closes) < 252:
        return []
    ret_12m = (closes[-1] - closes[-252]) / closes[-252]
    sma200 = mean(closes[-200:])
    if ret_12m > 0.03 and closes[-1] > sma200:
        conf = min(0.80, 0.5 + ret_12m)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"GEM: 12m return {ret_12m:.2%} > 3% T-bill proxy and above SMA200",
            strategy=STRATEGY_NAME,
        )]
    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    """Backwards-compat shim."""
    sigs = _v1_signals(symbol, closes)
    return sigs[0] if sigs else None
