"""Bull call debit spread: buy lower strike call, sell higher strike call. Directional bullish."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "bull_call_debit_spread"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: strong uptrend suggests bullish debit spread."""
    if len(closes) < 20:
        return []
    sma20 = mean(closes[-20:])
    strong_uptrend = closes[-1] > sma20 * 1.03
    if strong_uptrend:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.65,
            size_hint=0.65,
            reason="Bull call debit spread: buy ATM call, sell 5-10% OTM call, net debit",
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
