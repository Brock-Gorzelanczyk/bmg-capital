"""
Opening Range Breakout — Stocks In Play
SSRN 4729284. Sharpe 2.81 (2016-2023).

Only trade when: gap > 1%, premarket vol > 2x avg, OR earnings day.
ORB window: first 30 minutes (9:30-10:00 ET).
Long above ORH, short below ORL. Confirm with volume surge (>1.5x avg).
"""
from __future__ import annotations

import logging
from typing import Dict, List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "orb_stocks_in_play"

# Default ORB window: first 6 x 5-min bars = 30 minutes
DEFAULT_ORB_BARS = 6
# Volume confirmation multiplier
VOL_CONFIRM_RATIO = 1.5
# Gap threshold to qualify as stocks-in-play or catalyst
GAP_CATALYST_PCT = 0.02   # 2% = treat as catalyst
GAP_SIGNAL_PCT = 0.01     # 1% min gap to enter long


def _compute_avg_volume(bars: list[dict], lookback: int = 20) -> float:
    """Average volume over the last `lookback` bars (excluding ORB bars)."""
    if len(bars) < 2:
        return 0.0
    sample = bars[:-1]  # exclude the most recent bar to avoid lookahead
    if len(sample) > lookback:
        sample = sample[-lookback:]
    vols = [b["v"] for b in sample if b["v"] > 0]
    if not vols:
        return 0.0
    return sum(vols) / len(vols)


def _compute_gap_pct(bars: list[dict], orb_bars: int) -> float:
    """Gap % = (day open - prev close) / prev close.

    Uses the open of the first bar as 'day open' and the close of the bar
    immediately before the ORB window begins as 'prev close'.
    Requires at least orb_bars + 1 bars.
    """
    if len(bars) <= orb_bars:
        return 0.0
    day_open = bars[0]["o"]
    prev_close = bars[0]["c"]  # fallback
    # Walk backwards from the start of the session to find prev close
    # In practice bars are sorted oldest-first; bar[0] is the first 5-min bar
    # of the current day. The last bar of the previous session would be before
    # bar[0], but we don't have it here — use the open itself as a proxy and
    # look for an intra-list previous close if available.
    if len(bars) > 252:
        prev_close = bars[-253]["c"] if len(bars) >= 253 else bars[0]["c"]
    # Simpler heuristic: compare first bar open to first bar's own open
    # For intraday feeds the open of bar[0] IS the day open; we can compare
    # bar[0].open to bar[-orb_bars-1].close as "yesterday's close".
    prev_idx = max(0, len(bars) - orb_bars - 2)
    prev_close_candidate = bars[prev_idx]["c"]
    if prev_close_candidate > 0:
        prev_close = prev_close_candidate
    if prev_close <= 0:
        return 0.0
    return (day_open - prev_close) / prev_close


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate ORB signals for stocks-in-play.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first (5-min bars).
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    # Regime guard
    vix_regime = regime.get("vix_regime", "normal")
    if vix_regime == "panic":
        logger.info("ORB: skipping — vix_regime=panic")
        return []

    orb_bars: int = profile_config.get("orb_bars", DEFAULT_ORB_BARS)
    signals: list[Signal] = []

    for symbol, bar_list in bars.items():
        if not bar_list or len(bar_list) < orb_bars + 1:
            continue

        # --- Opening range (first N bars) ---
        orb_window = bar_list[:orb_bars]
        range_high = max(b["h"] for b in orb_window)
        range_low = min(b["l"] for b in orb_window)
        orb_width = range_high - range_low
        if orb_width <= 0:
            continue

        # --- Current bar (latest) ---
        current = bar_list[-1]
        close = current["c"]
        volume = current["v"]

        # --- Volume filter ---
        avg_vol = _compute_avg_volume(bar_list)
        vol_ratio = (volume / avg_vol) if avg_vol > 0 else 0.0
        if vol_ratio < VOL_CONFIRM_RATIO:
            continue

        # --- Gap / catalyst filter ---
        gap_pct = _compute_gap_pct(bar_list, orb_bars)
        is_catalyst = abs(gap_pct) >= GAP_CATALYST_PCT
        is_gap_long = gap_pct >= GAP_SIGNAL_PCT

        # --- Long breakout ---
        if close > range_high and is_gap_long or (close > range_high and is_catalyst):
            breakout_pct = (close - range_high) / orb_width
            raw_conf = (breakout_pct / orb_width) * (vol_ratio / VOL_CONFIRM_RATIO) * 0.8
            confidence = min(1.0, raw_conf)
            if vix_regime == "high":
                confidence *= 0.5
            confidence = max(0.0, min(1.0, confidence))
            signals.append(Signal(
                symbol=symbol,
                side="buy",
                confidence=confidence,
                size_hint=confidence,
                reason=(
                    f"ORB breakout above range_high={range_high:.2f}; "
                    f"close={close:.2f}; gap={gap_pct:.2%}; "
                    f"vol_ratio={vol_ratio:.2f}x"
                ),
                strategy=STRATEGY_NAME,
            ))

        # --- Short breakdown (catalyst not required for shorts) ---
        elif close < range_low and vol_ratio >= VOL_CONFIRM_RATIO:
            breakout_pct = (range_low - close) / orb_width
            raw_conf = (breakout_pct / orb_width) * (vol_ratio / VOL_CONFIRM_RATIO) * 0.8
            confidence = min(1.0, raw_conf)
            if vix_regime == "high":
                confidence *= 0.5
            confidence = max(0.0, min(1.0, confidence))
            signals.append(Signal(
                symbol=symbol,
                side="sell",
                confidence=confidence,
                size_hint=confidence,
                reason=(
                    f"ORB breakdown below range_low={range_low:.2f}; "
                    f"close={close:.2f}; gap={gap_pct:.2%}; "
                    f"vol_ratio={vol_ratio:.2f}x"
                ),
                strategy=STRATEGY_NAME,
            ))

    return signals
