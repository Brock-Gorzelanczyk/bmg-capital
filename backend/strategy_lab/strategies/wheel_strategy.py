"""Wheel strategy: sell cash-secured puts in uptrend, then covered calls if assigned."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "wheel_strategy"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: sell CSP when near support in uptrend."""
    if len(closes) < 20:
        return []
    sma20 = mean(closes[-20:])
    deviation = (closes[-1] - sma20) / sma20 if sma20 > 0 else 0
    in_uptrend = closes[-1] > closes[-40] if len(closes) >= 40 else True
    if -0.08 <= deviation <= -0.02 and in_uptrend:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.70,
            size_hint=0.70,
            reason=f"Wheel: sell 30d CSP at current strike, deviation={deviation:.2%} from SMA20",
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
