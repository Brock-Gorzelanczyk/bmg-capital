"""Quality minus junk (lite): consistent win rate + limited drawdown proxy."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "quality_minus_junk_lite"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: high daily win rate + drawdown not too deep = quality proxy."""
    if len(closes) < 252:
        return []
    win_rate_252 = sum(1 for i in range(-252, 0) if closes[i] > closes[i - 1]) / 252
    peak_52w = max(closes[-252:])
    drawdown_1y = (closes[-1] - peak_52w) / peak_52w if peak_52w > 0 else -1
    if win_rate_252 > 0.53 and drawdown_1y > -0.20:
        conf = min(0.75, win_rate_252 * 1.3)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"QMJ lite: win_rate={win_rate_252:.2%}, drawdown={drawdown_1y:.2%}",
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
