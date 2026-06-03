"""Betting against beta (long-only): low-vol assets outperform risk-adjusted."""
from __future__ import annotations
import logging
from statistics import stdev
from typing import List, Optional
from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "betting_against_beta_long_only"


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Core logic: buy low realized volatility stocks (low-beta proxy)."""
    if len(closes) < 60:
        return []
    returns_20 = [closes[i] / closes[i - 1] - 1 for i in range(-20, 0)]
    vol = stdev(returns_20) if len(returns_20) > 1 else 0.02
    if vol < 0.015:
        conf = min(0.70, (0.02 - vol) * 30)
        return [Signal(
            symbol=symbol, side="buy", confidence=conf,
            size_hint=conf,
            reason=f"BAB long-only: low realized vol {vol:.4f} < 0.015 threshold",
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
