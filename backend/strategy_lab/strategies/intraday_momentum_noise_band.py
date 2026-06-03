"""
Intraday Momentum with Noise Band Filter
SSRN 4824172. Sharpe 1.33-3.0.

Momentum signal: return from open to current bar > noise_band_pct.
Noise band = ATR(14, intraday) * noise_factor (default 0.3).
Long if return > noise_band AND trend up (price > VWAP).
Short if return < -noise_band AND trend down (price < VWAP).
Filter: don't trade last 30min (3:30pm+ ET) or first 5min.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "intraday_momentum_noise_band"

# Time-of-day bar index guards (assuming 5-min bars, market 9:30-16:00 ET)
# Bar 0  = 9:30-9:35  (skip first 5min = skip bar 0)
# Bar 77 = 15:25-15:30 (last tradeable; bar 78+ = skip last 30min = bars 78-77)
# 6.5 hours = 78 bars; skip first 1 and last 6
SKIP_FIRST_BARS = 1
SKIP_LAST_BARS = 6   # last 30 min = 6 x 5-min bars

# Noise factor: noise_band = intraday_atr * NOISE_FACTOR
NOISE_FACTOR = 0.3
ATR_WINDOW = 14


def _compute_vwap(bar_list: list[dict]) -> float:
    """VWAP = sum(v * typical_price) / sum(v).  Typical price = (h+l+c)/3."""
    cum_pv = 0.0
    cum_v = 0.0
    for b in bar_list:
        tp = (b["h"] + b["l"] + b["c"]) / 3.0
        cum_pv += tp * b["v"]
        cum_v += b["v"]
    if cum_v <= 0:
        return 0.0
    return cum_pv / cum_v


def _compute_intraday_atr(bar_list: list[dict], window: int = ATR_WINDOW) -> float:
    """Average of (high - low) for each bar over the last `window` bars."""
    sample = bar_list[-window:] if len(bar_list) >= window else bar_list
    ranges = [b["h"] - b["l"] for b in sample if b["h"] > b["l"]]
    if not ranges:
        return 0.0
    return sum(ranges) / len(ranges)


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate intraday momentum signals with noise band filter.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first (5-min bars).
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    vix_regime = regime.get("vix_regime", "normal")
    if vix_regime == "panic":
        logger.info("Momentum noise band: skipping — vix_regime=panic")
        return []

    noise_factor: float = profile_config.get("noise_factor", NOISE_FACTOR)
    signals: list[Signal] = []

    for symbol, bar_list in bars.items():
        if not bar_list or len(bar_list) < ATR_WINDOW + SKIP_FIRST_BARS:
            continue

        total_bars = len(bar_list)

        # Time-of-day guard: skip first bar and last 30 min
        if total_bars <= SKIP_FIRST_BARS:
            continue
        if total_bars > (78 - SKIP_LAST_BARS):
            # We're in the last 30 min window — skip
            continue

        # Open price = first bar's open
        open_price = bar_list[0]["o"]
        if open_price <= 0:
            continue

        current = bar_list[-1]
        close = current["c"]

        # Intraday return from open
        intraday_return = (close - open_price) / open_price

        # VWAP from all bars so far
        vwap = _compute_vwap(bar_list)
        if vwap <= 0:
            continue

        # Noise band
        intraday_atr = _compute_intraday_atr(bar_list)
        if intraday_atr <= 0:
            continue
        noise_band = (intraday_atr / open_price) * noise_factor

        # Confidence based on how far return exceeds noise band
        abs_return = abs(intraday_return)
        if abs_return <= noise_band:
            continue

        conf = min(1.0, abs_return / (noise_band * 2.0))
        if vix_regime == "high":
            conf *= 0.7
        conf = max(0.0, min(1.0, conf))

        # Long signal
        if intraday_return > noise_band and close > vwap:
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=conf,
                size_hint=conf,
                reason=(
                    f"Intraday momentum long: return={intraday_return:.2%} > "
                    f"noise_band={noise_band:.2%}; close={close:.2f} > vwap={vwap:.2f}"
                ),
                strategy=STRATEGY_NAME,
            ))

        # Short signal
        elif intraday_return < -noise_band and close < vwap:
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=conf,
                size_hint=conf,
                reason=(
                    f"Intraday momentum short: return={intraday_return:.2%} < "
                    f"-noise_band={-noise_band:.2%}; close={close:.2f} < vwap={vwap:.2f}"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
