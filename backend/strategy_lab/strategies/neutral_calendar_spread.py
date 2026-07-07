"""Neutral calendar spread: sell near-term ATM, buy far-term ATM. Profits from theta."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "neutral_calendar_spread"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: low recent volatility favors calendar spread entry."""
    if len(closes) < 5:
        return []
    max_move = max(abs(closes[i] - closes[i - 1]) for i in range(-5, 0))
    recent_vol_low = closes[-1] > 0 and max_move < closes[-1] * 0.03
    if recent_vol_low:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.60,
            size_hint=0.60,
            reason="Calendar spread: sell 30d ATM option, buy 60d ATM option, profit on time decay",
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
