"""Value + momentum + quality blend: all three factors must align."""
from __future__ import annotations
import logging
from statistics import mean
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "value_momentum_quality_blend"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: value AND momentum AND quality all positive."""
    if len(closes) < 252:
        return []
    avg_52w = mean(closes[-252:])
    value = closes[-1] < avg_52w * 0.98
    momentum = (closes[-1] - closes[-126]) / closes[-126] > 0.05 if closes[-126] > 0 else False
    win_rate_60 = sum(1 for i in range(-60, 0) if closes[i] > closes[i - 1]) / 60
    quality = win_rate_60 > 0.53
    if value and momentum and quality:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.78,
            size_hint=0.78,
            reason=f"VMQ blend: value={value}, momentum=True, quality_wr={win_rate_60:.2%}",
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
