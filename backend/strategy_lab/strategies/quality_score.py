"""Quality Score strategy — long high-quality stocks via consistency + low drawdown."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "quality_score"
MIN_WIN_RATE = 0.55
MAX_DRAWDOWN = -0.15


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Return buy on high-quality price behavior proxy.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 252.
    """
    if len(closes) < 252:
        return []

    window = closes[-252:]
    win_days = sum(1 for i in range(1, len(window)) if window[i] > window[i - 1])
    return_consistency = win_days / 251

    peak = max(window)
    current = window[-1]
    drawdown = (current - peak) / peak if peak != 0 else -1.0

    annual_up = closes[-1] > closes[-252]

    if return_consistency > MIN_WIN_RATE and drawdown > MAX_DRAWDOWN and annual_up:
        confidence = max(0.4, min(0.85, return_consistency))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Quality: win_rate {return_consistency*100:.1f}%, "
                f"drawdown {drawdown*100:.1f}% (above -{abs(MAX_DRAWDOWN)*100:.0f}% threshold)"
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
