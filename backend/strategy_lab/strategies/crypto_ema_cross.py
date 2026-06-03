"""Crypto EMA Cross strategy — 9 EMA / 21 EMA daily crossover with BTC trend filter."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_ema_cross"


def _ema(values: list[float], period: int) -> float:
    """Compute final EMA value for a price series."""
    if not values or period <= 0:
        return 0.0
    k = 2.0 / (period + 1)
    result = values[0]
    for v in values[1:]:
        result = v * k + result * (1 - k)
    return result


def _v1_signals(
    symbol: str,
    closes: list[float],
    regime: dict | None = None,
) -> List[Signal]:
    """Return buy/sell on 9/21 EMA crossover with bear regime filter.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 22.
        regime: Regime dict for trend gating.
    """
    if len(closes) < 22:
        return []

    ema9_curr = _ema(closes, 9)
    ema21_curr = _ema(closes, 21)
    ema9_prev = _ema(closes[:-1], 9)
    ema21_prev = _ema(closes[:-1], 21)

    bullish_cross = ema9_prev < ema21_prev and ema9_curr > ema21_curr
    bearish_cross = ema9_prev > ema21_prev and ema9_curr < ema21_curr

    if bullish_cross:
        if regime and regime.get("trend_regime") == "bear":
            return []
        spread = abs(ema9_curr - ema21_curr) / ema21_curr if ema21_curr != 0 else 0.0
        confidence = max(0.45, min(0.85, 0.5 + spread * 20))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Crypto EMA cross bullish: EMA9 {ema9_curr:.4f} crossed above "
                f"EMA21 {ema21_curr:.4f}"
            ),
            strategy=STRATEGY_NAME,
        )]

    if bearish_cross:
        spread = abs(ema9_curr - ema21_curr) / ema21_curr if ema21_curr != 0 else 0.0
        confidence = max(0.45, min(0.85, 0.5 + spread * 20))
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Crypto EMA cross bearish: EMA9 {ema9_curr:.4f} crossed below "
                f"EMA21 {ema21_curr:.4f}"
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
        out.extend(_v1_signals(symbol, closes, regime))
    return out


def generate_signal(symbol: str, closes: list[float]) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes)
    return signals[0] if signals else None
