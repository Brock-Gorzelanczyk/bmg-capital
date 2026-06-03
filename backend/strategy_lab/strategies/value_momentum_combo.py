"""Value + momentum combo: AMP 2013 blend of value rank and momentum rank."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "value_momentum_combo"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: positive 12-1m momentum and below 52w mean (value signal)."""
    if len(closes) < 252:
        return []
    mom_12_1 = (closes[-21] - closes[-252]) / closes[-252]
    avg_52w = mean(closes[-252:])
    value_signal = closes[-1] < avg_52w * 0.95
    if mom_12_1 > 0.05 and value_signal:
        conf = min(0.75, 0.5 + mom_12_1 * 2)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Value+momentum: 12-1m={mom_12_1:.2%}, price {closes[-1]:.2f} < 52w avg {avg_52w:.2f}*0.95",
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
