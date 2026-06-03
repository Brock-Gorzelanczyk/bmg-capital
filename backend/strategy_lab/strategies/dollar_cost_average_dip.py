"""Dollar Cost Average Dip strategy — extra DCA on >10% drawdown from 30d high."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "dollar_cost_average_dip"
DRAWDOWN_TRIGGER = -0.10   # -10% from rolling 30d high
LOOKBACK = 30


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Return buy on drawdown from 30-day rolling high.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 30.
    """
    if len(closes) < LOOKBACK:
        return []

    rolling_high = max(closes[-LOOKBACK:])
    current = closes[-1]

    if rolling_high == 0:
        return []

    drawdown = (current - rolling_high) / rolling_high

    if drawdown <= DRAWDOWN_TRIGGER:
        confidence = max(0.5, min(0.9, abs(drawdown) * 5))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"DCA dip buy: {drawdown*100:.1f}% drawdown from "
                f"30d high {rolling_high:.4f} (current {current:.4f})"
            ),
            strategy=STRATEGY_NAME,
        )]

    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py."""
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes))
    return out


def generate_signal(symbol: str, closes: list[float]) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes)
    return signals[0] if signals else None
