"""Iron condor 45 DTE: sell OTM put spread + OTM call spread for premium."""
from __future__ import annotations
import logging
from statistics import stdev
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "iron_condor_45dte"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: range-bound + low realized vol = iron condor entry."""
    if len(closes) < 21:
        return []
    daily_rets = [closes[i] / closes[i - 1] - 1 for i in range(-20, 0)]
    vol_20 = stdev(daily_rets) if len(daily_rets) > 1 else 0.02
    low_20 = min(closes[-20:])
    high_20 = max(closes[-20:])
    range_bound = closes[-1] > low_20 * 1.02 and closes[-1] < high_20 * 0.98
    if range_bound and vol_20 < 0.025:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.68,
            size_hint=0.68,
            reason="Iron condor 45 DTE: sell OTM put spread + call spread, 16-30 delta short strikes",
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
        out.extend(_v1_signals(symbol, closes))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    """Backwards-compat shim."""
    sigs = _v1_signals(symbol, closes)
    return sigs[0] if sigs else None
