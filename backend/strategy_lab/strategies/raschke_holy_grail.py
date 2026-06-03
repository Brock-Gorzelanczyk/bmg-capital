"""Raschke Holy Grail: ADX proxy > 30 + pullback to 20d EMA + resumption."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "raschke_holy_grail"


def _ema(prices: list[float], period: int) -> float:
    """Compute EMA for last value."""
    if not prices:
        return 0.0
    k = 2 / (period + 1)
    val = prices[0]
    for p in prices[1:]:
        val = p * k + val * (1 - k)
    return val


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: ADX proxy trend + pullback to EMA20 + resumption day."""
    if len(closes) < 22:
        return []
    ema20 = _ema(closes[-22:], 20)
    returns_14 = [closes[i] - closes[i - 1] for i in range(-14, 0)]
    updays = sum(1 for r in returns_14 if r > 0)
    adx_proxy = abs(updays - 7)
    pullback_to_ema = closes[-3] > ema20 and closes[-2] < ema20 * 1.005
    resumption = closes[-1] > closes[-2]
    if adx_proxy >= 5 and pullback_to_ema and resumption:
        return [Signal(
            symbol=symbol, side="buy", confidence=0.72,
            size_hint=0.72,
            reason=f"Raschke Holy Grail: ADX proxy={adx_proxy}, EMA20 pullback, resuming",
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
