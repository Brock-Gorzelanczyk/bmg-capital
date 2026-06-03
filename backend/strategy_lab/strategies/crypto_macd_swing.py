"""Crypto MACD Swing strategy — MACD crossover on 4h bars for top-30 crypto."""
from __future__ import annotations

import logging
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_macd_swing"


def _ema(values: list[float], period: int) -> list[float]:
    """Compute EMA series for the full values list."""
    if not values or period <= 0:
        return []
    k = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


def _v1_signals(symbol: str, closes: list[float], regime: dict | None = None) -> List[Signal]:
    """Return buy/sell on MACD crossover with bear-market filter.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last. Requires len >= 36.
        regime: Regime dict for trend gating.
    """
    if len(closes) < 36:
        return []

    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    macd_series = [e12 - e26 for e12, e26 in zip(ema12, ema26)]

    if len(macd_series) < 10:
        return []

    signal_series = _ema(macd_series, 9)

    if len(signal_series) < 2:
        return []

    prev_macd = macd_series[-2]
    curr_macd = macd_series[-1]
    prev_sig = signal_series[-2]
    curr_sig = signal_series[-1]
    histogram = curr_macd - curr_sig

    if prev_macd < prev_sig and curr_macd > curr_sig:
        # Skip buy signals in crypto bear regime
        if regime and regime.get("trend_regime") == "bear":
            return []
        confidence = max(0.4, min(0.85, abs(histogram) * 30 + 0.4))
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"Crypto MACD swing buy: histogram {histogram:.6f}",
            strategy=STRATEGY_NAME,
        )]

    if prev_macd > prev_sig and curr_macd < curr_sig:
        confidence = max(0.4, min(0.85, abs(histogram) * 30 + 0.4))
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=confidence,
            size_hint=confidence,
            reason=f"Crypto MACD swing sell: histogram {histogram:.6f}",
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
