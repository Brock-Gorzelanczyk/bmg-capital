"""Momentum Breakout strategy.

Buy when price breaks above the 20-day high on above-average volume.
Signal when: close > max(close[-20:]) AND volume > 1.5 * avg_volume_20.
Confidence: (close - prev_high) / prev_high * 10, clamped 0.4-0.9.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "momentum_breakout"
# 2026-07-13 fire-more relaxation: stock_swing + stock_momentum_breakout
# were producing 0 signals in 24h at PERIOD=20, VOLUME_MULTIPLIER=1.5.
# 20-day high + 1.5× volume is rare — the two conditions rarely coincide.
# Relaxed to 10-day highs + 1.1× volume so the gate is closer to the
# market baseline. Discipline gate still filters low-conviction downstream.
PERIOD = 10
VOLUME_MULTIPLIER = 1.1


def _v1_signals(
    symbol: str,
    closes: list[float],
    volumes: list[float],
) -> List[Signal]:
    """Return Signals for OHLCV close+volume series.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last.
        volumes: Volume values, most-recent last (same length as closes).
    """
    if len(closes) < PERIOD + 1 or len(volumes) < PERIOD + 1:
        return []

    current_close = closes[-1]
    current_volume = volumes[-1]

    # 20-day high uses bars[-21:-1] (the *previous* 20 bars, not including current)
    prev_closes = closes[-(PERIOD + 1):-1]
    prev_high = max(prev_closes)
    avg_volume = sum(volumes[-(PERIOD + 1):-1]) / PERIOD

    price_breakout = current_close > prev_high
    volume_confirm = avg_volume > 0 and current_volume > VOLUME_MULTIPLIER * avg_volume

    if price_breakout and volume_confirm:
        raw_conf = (current_close - prev_high) / prev_high * 10
        confidence = max(0.4, min(0.9, raw_conf))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Momentum breakout: {current_close:.2f} > 20d-high {prev_high:.2f} "
                f"on {current_volume / avg_volume:.1f}x avg volume"
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
        volumes = [float(b.get("v", 0)) for b in bar_list]
        out.extend(_v1_signals(symbol, closes, volumes))
    return out


# Backwards-compat shim
def generate_signal(
    symbol: str,
    current_price: float,
    recent_high: float,
    avg_volume: float,
    current_volume: float,
    volume_multiplier: float = VOLUME_MULTIPLIER,
) -> Optional[Signal]:
    """Single-value convenience wrapper (kept for backwards compatibility)."""
    if recent_high <= 0:
        return None
    price_breakout = current_price > recent_high
    volume_confirm = avg_volume > 0 and (current_volume / avg_volume) >= volume_multiplier
    if price_breakout and volume_confirm:
        raw_conf = (current_price - recent_high) / recent_high * 10
        confidence = max(0.4, min(0.9, raw_conf))
        return Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Momentum breakout: {current_price:.2f} > high {recent_high:.2f} "
                f"on {current_volume / avg_volume:.1f}x avg volume"
            ),
            strategy=STRATEGY_NAME,
        )
    return None
