"""
First Half-Hour Predicts Last Hour
Based on academic evidence: the first 30min return predicts last-hour direction.
If first 30min is strongly positive (>0.5%), probability of 3:00-4:00pm
continuation is ~62%.

Signal (only fires in last 90min of session, 2:30pm ET+):
  - Compute return from open to end of first 30min
  - If return > 0.5%: emit buy signal at 2:30pm for SPY/QQQ
  - If return < -0.5%: emit sell signal at 2:30pm for SPY/QQQ
  - confidence = min(1.0, abs(first_30min_return) / 0.01) * 0.7

Only applies to SPY, QQQ (index ETFs).
Only fires between 2:30pm and 3:00pm ET.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, time
from zoneinfo import ZoneInfo

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "first_half_hour_predicts_last"

ET_TZ = ZoneInfo("America/New_York")

# Only applies to these index ETFs
TARGET_SYMBOLS = frozenset({"SPY", "QQQ"})

# Signal firing window
SIGNAL_WINDOW_START = time(14, 30)  # 2:30pm ET
SIGNAL_WINDOW_END = time(15, 0)    # 3:00pm ET

# First 30min return thresholds
BULLISH_THRESHOLD = 0.005   # +0.5%
BEARISH_THRESHOLD = -0.005  # -0.5%

# Normalisation: return of 1% → confidence 0.7
RETURN_NORM = 0.01
MAX_CONFIDENCE = 0.70


def _bar_et_time(bar: dict) -> time | None:
    """Extract ET wall-clock time from bar timestamp."""
    ts_raw = bar.get("t")
    if not ts_raw:
        return None
    try:
        if isinstance(ts_raw, (int, float)):
            dt_utc = datetime.fromtimestamp(ts_raw, tz=timezone.utc)
        elif isinstance(ts_raw, str):
            dt_utc = datetime.fromisoformat(ts_raw.replace("Z", "+00:00"))
        elif isinstance(ts_raw, datetime):
            dt_utc = ts_raw if ts_raw.tzinfo else ts_raw.replace(tzinfo=timezone.utc)
        else:
            return None
        return dt_utc.astimezone(ET_TZ).time()
    except (ValueError, OSError, OverflowError):
        return None


def _is_in_signal_window(bar_list: list[dict]) -> bool:
    """Return True if the latest bar is in the 2:30-3:00pm ET window."""
    if not bar_list:
        return False
    latest = bar_list[-1]
    bar_time = _bar_et_time(latest)
    if bar_time is not None:
        return SIGNAL_WINDOW_START <= bar_time <= SIGNAL_WINDOW_END
    # Fallback: bars 85-90 in a 5-min intraday series ≈ 2:30-3:00pm ET
    n = len(bar_list)
    return 85 <= n <= 90


def _get_open_price(bar_list: list[dict]) -> float | None:
    """Return the session open (first bar's open price)."""
    if not bar_list:
        return None
    first_bar = bar_list[0]
    return first_bar.get("o", first_bar.get("open"))


def _get_first_30min_close(bar_list: list[dict]) -> float | None:
    """
    Return the close of the 6th bar (end of 9:30-10:00am ET window).
    Falls back to bar index 5 if no timestamps available.
    """
    session_end_30 = time(10, 0)
    session_start = time(9, 30)

    timestamped = [b for b in bar_list if _bar_et_time(b) is not None]
    if timestamped:
        first_30_bars = [b for b in timestamped if session_start <= _bar_et_time(b) <= session_end_30]
        if not first_30_bars:
            return None
        last_bar = first_30_bars[-1]
        return last_bar.get("c", last_bar.get("close"))

    # Fallback: bar index 5 (6th bar = end of first 30min)
    if len(bar_list) > 5:
        bar = bar_list[5]
        return bar.get("c", bar.get("close"))
    return None


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate first-half-hour-predicts-last-hour signals for SPY and QQQ.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first.
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, ...}.
    """
    signals: list[Signal] = []

    for symbol in TARGET_SYMBOLS:
        bar_list = bars.get(symbol)
        if not bar_list or len(bar_list) < 6:
            continue

        if not _is_in_signal_window(bar_list):
            continue

        session_open = _get_open_price(bar_list)
        first_30_close = _get_first_30min_close(bar_list)

        if not session_open or not first_30_close or session_open <= 0:
            continue

        first_30_return = (first_30_close - session_open) / session_open

        if first_30_return > BULLISH_THRESHOLD:
            side = "buy"
        elif first_30_return < BEARISH_THRESHOLD:
            side = "sell"
        else:
            # Return not strong enough to predict direction
            continue

        confidence = min(1.0, abs(first_30_return) / RETURN_NORM) * MAX_CONFIDENCE
        confidence = max(0.0, min(1.0, confidence))

        reason = (
            f"First-half-hour predicts last hour: {symbol} first-30min return "
            f"{first_30_return * 100:.2f}% ({'above' if side == 'buy' else 'below'} "
            f"{abs(BULLISH_THRESHOLD) * 100:.1f}% threshold); "
            f"entering {side} at 2:30pm ET"
        )

        signals.append(Signal(
            symbol=symbol,
            side=side,
            confidence=confidence,
            size_hint=round(confidence * 0.75, 3),
            reason=reason,
            strategy=STRATEGY_NAME,
        ))

    return signals
