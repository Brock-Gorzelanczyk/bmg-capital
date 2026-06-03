"""Bull put credit spread: sell higher put, buy lower put. ~70% win rate."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "bull_put_credit_spread"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: initiate bull put spread when not in sharp downtrend."""
    if len(closes) < 14:
        return []
    ret_2w = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0
    if ret_2w > -0.02:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.70,
            size_hint=0.70,
            reason="Bull put spread: sell 30d OTM put, buy further OTM put, collect net credit",
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
