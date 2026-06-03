"""Low Volatility Anomaly strategy — buy low-realized-vol stocks in uptrend."""
from __future__ import annotations

import logging
import math
from statistics import stdev
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "low_vol_anomaly"
VOL_THRESHOLD = 0.15  # annualized realized vol threshold


def _v1_signals(symbol: str, closes: list[float]) -> List[Signal]:
    """Return buy on low realized volatility + uptrend confirmation.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 252.
    """
    if len(closes) < 252:
        return []

    daily_returns = [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(len(closes) - 251, len(closes))
        if closes[i - 1] != 0
    ]

    if len(daily_returns) < 2:
        return []

    realized_vol_daily = stdev(daily_returns)
    realized_vol_annual = realized_vol_daily * math.sqrt(252)

    trending_up = closes[-1] > closes[-20]

    if realized_vol_annual < VOL_THRESHOLD and trending_up:
        confidence = max(0.3, min(0.75, (0.20 - realized_vol_annual) * 5))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Low-vol anomaly: realized vol {realized_vol_annual*100:.1f}% "
                f"< {VOL_THRESHOLD*100:.0f}% threshold; price trending up"
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
