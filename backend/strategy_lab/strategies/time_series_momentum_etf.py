"""Time-series momentum for ETFs: long if 12-month return > 0, else exit/short."""
from __future__ import annotations
import logging
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "time_series_momentum_etf"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: 12-month absolute momentum."""
    if len(closes) < 252:
        return []
    ret_12m = (closes[-1] - closes[-252]) / closes[-252]
    if ret_12m > 0:
        conf = min(0.85, 0.5 + ret_12m * 2)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf, reason=f"12m return {ret_12m:.2%} > 0, time-series momentum long",
            strategy=STRATEGY_NAME,
        )]
    if ret_12m < -0.05:
        conf = min(0.80, 0.5 + abs(ret_12m) * 2)
        return [Signal(
            symbol=symbol, side="sell", confidence=conf,
            size_hint=conf, reason=f"12m return {ret_12m:.2%} < -5%, exit/short signal",
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
