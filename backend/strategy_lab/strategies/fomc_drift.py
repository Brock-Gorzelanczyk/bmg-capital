"""
FOMC Drift Strategy
Sharpe 0.6-1.07.

SPY tends to drift higher in the 2h after FOMC announcement (1-3pm ET
on FOMC days when statement releases at 2pm ET, press conf 2:30pm).
Enter SPY/QQQ long at 2:05pm ET on FOMC days. Exit by 4pm.
Only active on FOMC days (check catalyst calendar).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone, time
from zoneinfo import ZoneInfo

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "fomc_drift"

# Fixed confidence based on historical win rate
FOMC_CONFIDENCE = 0.65

# Entry window: 2:05pm - 2:30pm ET (bars 85-91 in a 5-min intraday series)
# Using wall-clock times; these are checked against the timestamp of the
# latest bar if timestamps are available, or approximated via bar index.
ENTRY_WINDOW_START = time(14, 5)   # 2:05pm ET
ENTRY_WINDOW_END = time(14, 30)    # 2:30pm ET

ET_TZ = ZoneInfo("America/New_York")

# Hardcoded 2025-2026 FOMC announcement dates (statement at 2pm ET)
FOMC_DATES: frozenset[date] = frozenset({
    # 2025
    date(2025, 1, 29),
    date(2025, 3, 19),
    date(2025, 5, 7),
    date(2025, 6, 18),
    date(2025, 7, 30),
    date(2025, 9, 17),
    date(2025, 10, 29),
    date(2025, 12, 10),
    # 2026
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
})

FOMC_SYMBOLS = ("SPY", "QQQ")


def _current_et_time() -> tuple[date, time]:
    """Return the current date and time in ET."""
    now_et = datetime.now(ET_TZ)
    return now_et.date(), now_et.time()


def _bar_et_time(bar: dict) -> time | None:
    """Extract ET time from bar timestamp if present."""
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


def _is_in_entry_window(bar_list: list[dict]) -> bool:
    """Return True if the latest bar falls in the 2:05-2:30pm ET window."""
    if not bar_list:
        return False
    latest_bar = bar_list[-1]
    bar_time = _bar_et_time(latest_bar)
    if bar_time is not None:
        return ENTRY_WINDOW_START <= bar_time <= ENTRY_WINDOW_END
    # Fallback: approximate via bar index (5-min bars from 9:30 ET open)
    # Bar index 85 ~ 2:05pm, bar index 90 ~ 2:30pm
    n = len(bar_list)
    return 85 <= n <= 91


def generate_signals(
    bars: dict[str, list[dict]],
    profile_config: dict,
    regime: dict,
) -> list[Signal]:
    """Generate FOMC drift signals for SPY and QQQ.

    bars: {symbol: [{t, o, h, l, c, v}, ...]} sorted oldest-first.
    profile_config: loaded YAML profile.
    regime: {vix_regime, trend_regime, vol_pctile, btc_dominance, btc_funding_rate}.
    """
    vix_regime = regime.get("vix_regime", "normal")
    if vix_regime == "panic":
        logger.info("FOMC drift: skipping — vix_regime=panic")
        return []

    # Check today's date
    today_et, _ = _current_et_time()
    if today_et not in FOMC_DATES:
        return []

    # Determine which of the target symbols are present in bars
    signals: list[Signal] = []

    for symbol in FOMC_SYMBOLS:
        bar_list = bars.get(symbol)
        if not bar_list:
            continue

        if not _is_in_entry_window(bar_list):
            continue

        confidence = FOMC_CONFIDENCE
        if vix_regime == "high":
            confidence *= 0.7
        confidence = max(0.0, min(1.0, confidence))

        signals.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"FOMC drift: {today_et} is FOMC day; entering {symbol} long 2:05-2:30pm ET",
            strategy=STRATEGY_NAME,
        ))

    return signals
