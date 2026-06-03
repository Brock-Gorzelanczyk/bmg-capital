"""Bear call credit spread: sell lower call, buy higher call. Profit when stock stays flat/down."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "bear_call_credit_spread"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: initiate bear call spread when not in sharp uptrend."""
    if len(closes) < 14:
        return []
    ret_2w = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0
    if ret_2w < 0.02:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.65,
            size_hint=0.65,
            reason="Bear call spread: sell 30d OTM call, buy higher strike call, net credit",
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
