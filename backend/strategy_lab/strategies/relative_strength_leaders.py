"""
Relative Strength Leaders (O'Neil / CAN SLIM inspired).
IBD RS Rating equivalent: 63d and 252d return vs universe.
Long top-decile RS stocks breaking out on volume.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "relative_strength_leaders"

# Lookback windows for RS score
RS_SHORT_BARS = 63    # ~3 months
RS_LONG_BARS = 252    # ~12 months

# SMA window for trend confirmation
SMA_WINDOW = 20

# Volume surge threshold
VOL_CONFIRM_RATIO = 1.5

# RS score percentile threshold to enter (top decile = 0.9)
RS_PERCENTILE_THRESHOLD = 0.90


def _compute_rs_score(bar_list: list[dict]) -> float | None:
    """RS score = average of 63d and 252d price return.

    Returns None if insufficient data.
    """
    closes = [b["c"] for b in bar_list]
    current = closes[-1]
    if current <= 0:
        return None

    short_return: float | None = None
    long_return: float | None = None

    if len(closes) >= RS_SHORT_BARS:
        base_short = closes[-RS_SHORT_BARS]
        if base_short > 0:
            short_return = (current - base_short) / base_short

    if len(closes) >= RS_LONG_BARS:
        base_long = closes[-RS_LONG_BARS]
        if base_long > 0:
            long_return = (current - base_long) / base_long

    if short_return is None and long_return is None:
        return None
    if short_return is None:
        return long_return
    if long_return is None:
        return short_return
    return (short_return + long_return) / 2.0


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
    """Generate RS leaders signals.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first (daily bars).
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    vix_regime = regime.get("vix_regime", "normal")
    trend_regime = regime.get("trend_regime", "neutral")

    if vix_regime == "panic":
        logger.info("RS leaders: skipping — vix_regime=panic")
        return []
    if trend_regime == "bear":
        logger.info("RS leaders: skipping — trend_regime=bear")
        return []

    # Compute RS scores for the full universe first (need median)
    rs_scores: dict[str, float] = {}
    for symbol, bar_list in bars.items():
        score = _compute_rs_score(bar_list)
        if score is not None:
            rs_scores[symbol] = score

    if not rs_scores:
        return []

    sorted_scores = sorted(rs_scores.values())
    n = len(sorted_scores)
    # Median for relative comparison
    median_rs = sorted_scores[n // 2]

    # Top decile threshold
    decile_idx = max(0, int(n * RS_PERCENTILE_THRESHOLD))
    top_decile_threshold = sorted_scores[decile_idx] if decile_idx < n else sorted_scores[-1]

    signals: list[Signal] = []

    for symbol, rs_score in rs_scores.items():
        if rs_score < top_decile_threshold:
            continue

        bar_list = bars[symbol]
        closes = [b["c"] for b in bar_list]
        volumes = [b["v"] for b in bar_list]

        current_close = closes[-1]
        sma20 = _compute_sma(closes, SMA_WINDOW)
        avg_vol = _compute_avg_vol(volumes)
        current_vol = volumes[-1]

        # Require price above SMA20 and volume surge
        if sma20 > 0 and current_close <= sma20:
            continue
        vol_surge = (current_vol / avg_vol) >= VOL_CONFIRM_RATIO if avg_vol > 0 else False
        if not vol_surge:
            continue

        # Confidence = relative rank within top decile
        # Normalise: how much above top_decile_threshold
        range_above = rs_score - top_decile_threshold
        score_range = max(sorted_scores) - top_decile_threshold
        confidence = (range_above / score_range) if score_range > 0 else 0.5
        confidence = max(0.2, min(0.95, confidence))

        if vix_regime == "high":
            confidence *= 0.75
        confidence = max(0.0, min(1.0, confidence))

        signals.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"RS leaders: rs_score={rs_score:.3f} (top decile >= {top_decile_threshold:.3f}); "
                f"close={current_close:.2f} > SMA20={sma20:.2f}; "
                f"vol_ratio={current_vol/avg_vol:.2f}x"
            ),
            strategy=STRATEGY_NAME,
        ))

    return signals
