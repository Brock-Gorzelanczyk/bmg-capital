"""VWAP Reversion Chop strategy — mean-revert to VWAP in choppy/range-bound markets."""
from __future__ import annotations

import logging
from statistics import mean, stdev
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "vwap_reversion_chop"
DEVIATION_THRESHOLD = 1.0  # percent from VWAP


def _v1_signals(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
    regime: dict | None = None,
) -> List[Signal]:
    """Return buy/sell when price deviates from VWAP in chop regime.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 14.
        highs: High prices, most-recent last.
        lows: Low prices, most-recent last.
        volumes: Volume values, most-recent last.
        regime: Optional regime dict for trend/VIX gating.
    """
    if len(closes) < 14 or len(highs) < 14 or len(lows) < 14 or len(volumes) < 14:
        return []

    # Gate on regime
    if regime:
        if regime.get("trend_regime") == "trend":
            return []
        if regime.get("vix_regime") == "panic":
            return []

    # Compute VWAP
    typical_prices = [(h + l + c) / 3 for h, l, c in zip(highs, lows, closes)]
    total_vol = sum(volumes)
    if total_vol == 0:
        return []
    vwap = sum(tp * v for tp, v in zip(typical_prices, volumes)) / total_vol

    # ADX-proxy chop detection: stable daily ranges
    daily_ranges = [h - l for h, l in zip(highs[-14:], lows[-14:])]
    avg_range = mean(daily_ranges)
    std_range = stdev(daily_ranges) if len(daily_ranges) > 1 else 0.0
    chop = avg_range > 0 and (std_range / avg_range) < 0.5

    if not chop:
        return []

    deviation_pct = (closes[-1] - vwap) / vwap * 100 if vwap != 0 else 0.0

    if deviation_pct <= -DEVIATION_THRESHOLD:
        confidence = max(0.4, min(0.8, abs(deviation_pct) * 0.2))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"VWAP chop reversion buy: {deviation_pct:.2f}% below VWAP {vwap:.2f}",
            strategy=STRATEGY_NAME,
        )]

    if deviation_pct >= DEVIATION_THRESHOLD:
        confidence = max(0.4, min(0.8, deviation_pct * 0.2))
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=f"VWAP chop reversion sell: {deviation_pct:.2f}% above VWAP {vwap:.2f}",
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
        highs = [float(b.get("h", 0)) for b in bar_list]
        lows = [float(b.get("l", 0)) for b in bar_list]
        volumes = [float(b.get("v", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, highs, lows, volumes, regime))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    volumes: list[float],
) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes, highs, lows, volumes)
    return signals[0] if signals else None
