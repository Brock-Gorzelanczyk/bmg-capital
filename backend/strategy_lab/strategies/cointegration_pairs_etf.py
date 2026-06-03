"""Cointegration pairs (ETF): mean reversion when price diverges >2 std from 20d mean."""
from __future__ import annotations
import logging
from statistics import mean, stdev
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "cointegration_pairs_etf"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: z-score vs 20d mean, revert when |z| > 2."""
    if len(closes) < 40:
        return []
    window = closes[-20:]
    m = mean(window)
    s = stdev(window) if len(window) > 1 else 1.0
    z = (closes[-1] - m) / s if s > 0 else 0.0
    if z < -2.0:
        conf = min(0.80, abs(z) * 0.25)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf, reason=f"Cointegration revert: z={z:.2f} < -2.0, buy",
            strategy=STRATEGY_NAME,
        )]
    if z > 2.0:
        conf = min(0.80, z * 0.25)
        return [Signal(
            symbol=symbol, side="sell", confidence=conf,
            size_hint=conf, reason=f"Cointegration revert: z={z:.2f} > 2.0, sell",
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
