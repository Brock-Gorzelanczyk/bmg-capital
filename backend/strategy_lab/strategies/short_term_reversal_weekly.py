"""Short-term reversal (weekly): buy prior week's biggest losers (Lehmann 1990)."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "short_term_reversal_weekly"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: buy if weekly return < -6%."""
    if len(closes) < 6:
        return []
    weekly_return = (closes[-1] - closes[-5]) / closes[-5]
    if weekly_return < -0.06:
        conf = min(0.75, abs(weekly_return) * 5)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Short-term reversal: weekly return {weekly_return:.2%} < -6%",
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
