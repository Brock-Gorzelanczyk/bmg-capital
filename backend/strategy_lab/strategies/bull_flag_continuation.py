"""Bull flag continuation: strong pole move then tight pullback before resumption."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "bull_flag_continuation"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: 5d pole up >5%, then 5d flag with slight pullback."""
    if len(closes) < 15:
        return []
    pole_return = (closes[-10] - closes[-15]) / closes[-15] if closes[-15] > 0 else 0
    flag_return = (closes[-1] - closes[-10]) / closes[-10] if closes[-10] > 0 else 0
    if pole_return > 0.05 and -0.03 < flag_return < 0.01:
        conf = min(0.75, pole_return * 5)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Bull flag: pole={pole_return:.2%}, flag={flag_return:.2%}",
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
