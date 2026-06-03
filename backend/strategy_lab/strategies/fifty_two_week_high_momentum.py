"""
52-Week High Momentum (George/Hwang 2004).
Stocks near 52-week high outperform over next 1-6 months.
Long when price within 2% of 52w high, volume confirming, uptrend intact.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "fifty_two_week_high_momentum"

# Daily bars required for a 52-week lookback
LOOKBACK_BARS = 252
SMA_WINDOW = 50
# Price must be within this fraction of the 52w high
NEARNESS_THRESHOLD = 0.98   # within 2%
# Volume must be above this multiple of average
VOL_CONFIRM_RATIO = 1.2


def _compute_sma(closes: list[float], window: int) -> float:
    """Simple moving average of the last `window` closes."""
    if len(closes) < window:
        return 0.0
    return sum(closes[-window:]) / window


def _compute_avg_vol(volumes: list[float], window: int = 20) -> float:
    """Average volume over `window` bars."""
    sample = volumes[-window:] if len(volumes) >= window else volumes
    if not sample:
        return 0.0
    return sum(sample) / len(sample)


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate 52-week high momentum signals.

    Requires ~252 daily bars per symbol.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first (daily bars).
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    vix_regime = regime.get("vix_regime", "normal")
    if vix_regime == "panic":
        logger.info("52w high momentum: skipping — vix_regime=panic")
        return []

    signals: list[Signal] = []

    for symbol, bar_list in bars.items():
        if len(bar_list) < LOOKBACK_BARS:
            logger.debug("52w high %s: insufficient bars (%d < %d)", symbol, len(bar_list), LOOKBACK_BARS)
            continue

        closes = [b["c"] for b in bar_list]
        volumes = [b["v"] for b in bar_list]

        current_close = closes[-1]
        max_52w = max(closes[-LOOKBACK_BARS:])
        sma50 = _compute_sma(closes, SMA_WINDOW)
        avg_vol = _compute_avg_vol(volumes)
        current_vol = volumes[-1]

        if max_52w <= 0 or sma50 <= 0:
            continue

        nearness = current_close / max_52w

        # Signal conditions
        near_high = nearness >= NEARNESS_THRESHOLD
        uptrend = current_close > sma50
        vol_confirmed = (current_vol / avg_vol) >= VOL_CONFIRM_RATIO if avg_vol > 0 else False

        if not (near_high and uptrend and vol_confirmed):
            continue

        # Confidence: how close to the 52w high (linearly from 0.98->1.0 maps to 0->1)
        confidence = (nearness - NEARNESS_THRESHOLD) / (1.0 - NEARNESS_THRESHOLD)
        confidence = max(0.1, min(1.0, confidence))

        if vix_regime == "high":
            confidence *= 0.7
        confidence = max(0.0, min(1.0, confidence))

        signals.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"52w high momentum: close={current_close:.2f} is "
                f"{nearness:.2%} of 52w_high={max_52w:.2f}; "
                f"above SMA50={sma50:.2f}; vol_ratio={current_vol/avg_vol:.2f}x"
            ),
            strategy=STRATEGY_NAME,
        ))

    return signals
