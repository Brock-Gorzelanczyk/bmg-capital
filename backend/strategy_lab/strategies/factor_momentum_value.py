"""
Factor Momentum + Value blend for stock_swing.
Long: stocks with positive 12-1 month momentum AND P/E below sector median.
Use price momentum as proxy for factor since P/E not available in paper phase.
12-1m momentum: return from 252 bars ago to 21 bars ago (skip last month).
"""
from __future__ import annotations

import logging
from typing import Dict, List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "factor_momentum_value"

# 12-1 month momentum window (daily bars)
MOMENTUM_LONG_BARS = 252   # 12 months ago
MOMENTUM_SHORT_BARS = 21   # 1 month ago (skipped, i.e. reference point)

# Value proxy: price well below 52-week high (cheap relative to recent peak)
VALUE_MAX_HIGH_RATIO = 0.85   # price <= 85% of 52w high = considered "value"

# Minimum positive momentum threshold
MIN_MOMENTUM = 0.05   # 5% over 12-1 month window

# SMA confirmation
SMA_WINDOW = 50


def _compute_12_1_momentum(closes: list[float]) -> float | None:
    """12-1 month price momentum: return from bar[-252] to bar[-21].

    Skips the most recent month to avoid short-term reversal.
    Returns None if insufficient data.
    """
    if len(closes) < MOMENTUM_LONG_BARS + 1:
        return None
    base = closes[-MOMENTUM_LONG_BARS]
    end = closes[-MOMENTUM_SHORT_BARS] if len(closes) > MOMENTUM_SHORT_BARS else closes[-1]
    if base <= 0:
        return None
    return (end - base) / base


def _compute_sma(closes: list[float], window: int) -> float:
    if len(closes) < window:
        return 0.0
    return sum(closes[-window:]) / window


def _compute_avg_vol(volumes: list[float], window: int = 20) -> float:
    sample = volumes[-window:] if len(volumes) >= window else volumes
    if not sample:
        return 0.0
    return sum(sample) / len(sample)


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate factor momentum + value signals.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first (daily bars).
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    vix_regime = regime.get("vix_regime", "normal")
    trend_regime = regime.get("trend_regime", "neutral")

    if vix_regime == "panic":
        logger.info("Factor mom+value: skipping — vix_regime=panic")
        return []

    signals: list[Signal] = []

    for symbol, bar_list in bars.items():
        if len(bar_list) < MOMENTUM_LONG_BARS + 1:
            continue

        closes = [b["c"] for b in bar_list]
        volumes = [b["v"] for b in bar_list]

        momentum_12_1 = _compute_12_1_momentum(closes)
        if momentum_12_1 is None or momentum_12_1 < MIN_MOMENTUM:
            continue

        # Value proxy: current price relative to 52w high
        max_52w = max(closes[-252:])
        current_close = closes[-1]
        high_ratio = current_close / max_52w if max_52w > 0 else 1.0

        value_discount = high_ratio <= VALUE_MAX_HIGH_RATIO

        sma50 = _compute_sma(closes, SMA_WINDOW)
        in_uptrend = current_close > sma50 if sma50 > 0 else False

        # Require either value discount OR uptrend (not necessarily both for swing)
        if not (value_discount or in_uptrend):
            continue

        avg_vol = _compute_avg_vol(volumes)
        current_vol = volumes[-1]
        vol_ratio = (current_vol / avg_vol) if avg_vol > 0 else 1.0

        # Confidence = blend of momentum strength and value discount
        momentum_conf = min(1.0, momentum_12_1 / 0.30)  # 30% momentum = full conf
        value_conf = (1.0 - high_ratio / VALUE_MAX_HIGH_RATIO) if value_discount else 0.3
        value_conf = max(0.0, min(1.0, value_conf))

        momentum_weight = 0.60
        value_weight = 0.40
        confidence = momentum_weight * momentum_conf + value_weight * value_conf
        confidence = max(0.2, min(1.0, confidence))

        if vix_regime == "high":
            confidence *= 0.75
        if trend_regime == "bear":
            confidence *= 0.50
        confidence = max(0.0, min(1.0, confidence))

        signals.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"Factor mom+value: 12-1m_mom={momentum_12_1:.2%}; "
                f"price_vs_52w={high_ratio:.2%}; "
                f"vol_ratio={vol_ratio:.2f}x"
            ),
            strategy=STRATEGY_NAME,
        ))

    return signals
