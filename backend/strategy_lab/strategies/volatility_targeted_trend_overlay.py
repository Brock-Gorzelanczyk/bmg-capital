"""Volatility-targeted trend overlay: scale position size by target vol / realized vol."""
from __future__ import annotations
import logging
import math
from statistics import mean, stdev
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "volatility_targeted_trend_overlay"
TARGET_VOL = 0.10  # 10% annualized target


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: trend signal scaled by vol target / realized vol."""
    if len(closes) < 21:
        return []
    daily_rets = [closes[i] / closes[i - 1] - 1 for i in range(-20, 0)]
    realized_vol = stdev(daily_rets) * math.sqrt(252) if len(daily_rets) > 1 else TARGET_VOL
    if len(closes) >= 200:
        trend = closes[-1] > mean(closes[-200:])
    else:
        trend = closes[-1] > closes[-20]
    if trend and realized_vol > 0:
        scale = min(2.0, TARGET_VOL / realized_vol)
        conf = min(0.85, 0.5 * scale)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"Vol-target overlay: realized_vol={realized_vol:.2%}, scale={scale:.2f}",
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
