"""Lottery stock avoidance: sell signal for high-vol, low-price, spike stocks."""
from __future__ import annotations
import logging
from statistics import stdev
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "lottery_stock_avoidance_max"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: identify and avoid lottery-like stocks (Bali/Cakici/Whitelaw 2011)."""
    if len(closes) < 20:
        return []
    daily_returns = [closes[i] / closes[i - 1] - 1 for i in range(-20, 0)]
    max_1d_gain = max(daily_returns)
    vol = stdev(daily_returns) if len(daily_returns) > 1 else 0
    if max_1d_gain > 0.15 and vol > 0.03 and closes[-1] < 15:
        return [Signal(
            symbol=symbol, side="sell", confidence=0.60,
            size_hint=0.60,
            reason=f"Lottery stock: max 1d gain={max_1d_gain:.2%}, vol={vol:.3f}, price={closes[-1]:.2f}",
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
