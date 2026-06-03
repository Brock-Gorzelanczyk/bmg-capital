"""
PEAD Intraday Drift
Sharpe 0.76-1.52.

After earnings, stocks with large gaps tend to continue drifting in
gap direction for the rest of the day (especially first 2h after open).
Long if gap > 3% AND holding within 50% of gap (not given it all back).
Confidence based on gap magnitude and drift sustainability.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "pead_intraday_drift"

# Minimum gap to qualify as PEAD setup
MIN_GAP_PCT = 0.03          # 3%
# Drift sustainability: stock must retain at least this fraction of the gap
DRIFT_RETENTION_THRESHOLD = 0.50
# First 2 hours = 24 x 5-min bars; signal only valid in this window
PEAD_MAX_BARS = 24
# Skip first bar (first 5 minutes)
SKIP_FIRST_BARS = 1


def _estimate_gap(bar_list: list[dict]) -> float:
    """Estimate gap % as (first_bar_open - prev_session_close) / prev_session_close.

    Since we only have intraday bars, we approximate prev_session_close using
    the close of bar_list[0] prior day. Without explicit cross-day data we use
    a heuristic: if bar_list has > 78 bars (more than one session) the close
    approximately 78 bars before bar[0] of today's session is yesterday's close.
    Otherwise fall back to bar[0].close as a conservative estimate (gap=0).
    """
    if not bar_list:
        return 0.0
    day_open = bar_list[0]["o"]
    # Attempt to find yesterday's close: bars are sorted oldest-first
    # If we have at least 79 bars, the bar at index -79 is approximately
    # last bar of the prior session.
    if len(bar_list) >= 79:
        prev_close = bar_list[-79]["c"]
    else:
        # Can't estimate — use a sentinel that results in gap=0
        prev_close = day_open
    if prev_close <= 0:
        return 0.0
    return (day_open - prev_close) / prev_close


def _compute_drift_retention(bar_list: list[dict], gap_pct: float) -> float:
    """How much of the gap has been retained so far.

    Returns fraction of gap still intact: 1.0 = fully retained, 0.0 = fully reversed.
    """
    if not bar_list or gap_pct == 0:
        return 0.0
    day_open = bar_list[0]["o"]
    current_close = bar_list[-1]["c"]
    intraday_return = (current_close - day_open) / day_open if day_open > 0 else 0.0
    # Retention = current intraday move / gap size
    # If stock is drifting in the same direction as gap, retention > 0
    if gap_pct > 0:
        return intraday_return / gap_pct
    else:
        return (-intraday_return) / abs(gap_pct)


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate PEAD intraday drift signals.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first (5-min bars).
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    vix_regime = regime.get("vix_regime", "normal")
    if vix_regime == "panic":
        logger.info("PEAD drift: skipping — vix_regime=panic")
        return []

    min_gap: float = profile_config.get("pead_min_gap_pct", MIN_GAP_PCT)
    signals: list[Signal] = []

    for symbol, bar_list in bars.items():
        if not bar_list or len(bar_list) < SKIP_FIRST_BARS + 1:
            continue

        # Only valid in first 2 hours of session
        if len(bar_list) > PEAD_MAX_BARS:
            continue

        gap_pct = _estimate_gap(bar_list)
        if abs(gap_pct) < min_gap:
            continue

        retention = _compute_drift_retention(bar_list, gap_pct)
        if retention < DRIFT_RETENTION_THRESHOLD:
            # Gap has been more than 50% reversed — PEAD thesis broken
            continue

        # Confidence: combination of gap magnitude and drift retention
        # Base: gap magnitude normalised to 10% (0.03->0.3, 0.10->1.0)
        gap_component = min(1.0, abs(gap_pct) / 0.10)
        # Retention premium
        retention_component = min(1.0, retention)
        confidence = min(1.0, gap_component * 0.6 + retention_component * 0.4)

        if vix_regime == "high":
            confidence *= 0.7
        confidence = max(0.0, min(1.0, confidence))

        side = "buy" if gap_pct > 0 else "sell"
        signals.append(Signal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"PEAD drift: gap={gap_pct:.2%} (>{min_gap:.0%}); "
                f"retention={retention:.0%} (>{DRIFT_RETENTION_THRESHOLD:.0%})"
            ),
            strategy=STRATEGY_NAME,
        ))

    return signals
