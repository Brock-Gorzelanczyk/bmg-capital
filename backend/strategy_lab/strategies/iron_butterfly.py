"""Iron butterfly: sell ATM straddle + buy OTM wings. Max premium, profit in tight range."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "iron_butterfly"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: tightest 5-day range in recent history = ideal butterfly setup."""
    if len(closes) < 20:
        return []
    recent_range = max(closes[-5:]) - min(closes[-5:])
    tightest_range = closes[-1] > 0 and recent_range < closes[-1] * 0.02
    if tightest_range:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65,
            reason="Iron butterfly: sell ATM straddle, buy OTM wings, max profit at expiry pin",
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
