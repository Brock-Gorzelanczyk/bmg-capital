"""Market-hours utilities for staleness calculations.

Bot signal "staleness" was wall-clock based, which caused false-positive
RED alerts every weekend for equity/options bots (markets closed Fri 16:00
ET → Mon 09:30 ET = ~65 calendar hours). This module provides RTH-aware
helpers so we only count time during NYSE regular trading hours.

Scope: NYSE RTH only (09:30-16:00 America/New_York, Mon-Fri).
- No holiday calendar (skipping that for now; a Thursday holiday is rare
  enough to not justify pulling in pandas_market_calendars).
- Asset classes:
    crypto / quant: 24/7 — staleness uses wall-clock minutes unchanged
    equity / options / stocks: RTH-only — staleness uses count_rth_minutes_between
    futures / other: defaults to wall-clock (no special handling yet)

Uses pytz (already a dep via bot_scheduler.py).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import Optional

try:
    import pytz
    _ET = pytz.timezone("America/New_York")
except Exception:  # pragma: no cover — pytz is in requirements but fail-safe
    _ET = None  # type: ignore[assignment]

# Asset classes that respect RTH (every other class is treated as 24/7 here)
_RTH_CLASSES = {"stock", "stocks", "equities", "equity", "options"}

_RTH_START = time(9, 30)
_RTH_END = time(16, 0)


def _to_et(dt: datetime) -> datetime:
    """Convert any aware/naive datetime to ET-aware. Naive is assumed UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if _ET is None:
        # Fallback: fixed -4h offset (EDT). Loses correctness across DST flips.
        return dt.astimezone(timezone(timedelta(hours=-4)))
    return dt.astimezone(_ET)


def is_trading_day(d) -> bool:
    """True if `d` (date or datetime) is a Mon-Fri. Holidays not yet handled."""
    if isinstance(d, datetime):
        d = d.date()
    return d.weekday() < 5


def is_market_open(dt: Optional[datetime] = None) -> bool:
    """True if `dt` (default: now UTC) is within NYSE RTH on a weekday."""
    et = _to_et(dt or datetime.now(timezone.utc))
    if not is_trading_day(et):
        return False
    return _RTH_START <= et.time() < _RTH_END


def count_rth_minutes_between(start: datetime, end: datetime) -> float:
    """Minutes of overlap between [start, end] and NYSE RTH.

    Walks the day-by-day intersection. For most realistic ranges this is
    < 10 iterations so a simple loop is fine. Returns 0.0 if start >= end.
    """
    if start is None or end is None:
        return 0.0
    s_et = _to_et(start)
    e_et = _to_et(end)
    if s_et >= e_et:
        return 0.0

    total_min = 0.0
    day = s_et.date()
    last_day = e_et.date()
    while day <= last_day:
        if is_trading_day(day):
            # Build the RTH window for this calendar day in ET
            rth_open = _ET.localize(datetime.combine(day, _RTH_START)) if _ET else datetime.combine(day, _RTH_START).replace(tzinfo=timezone(timedelta(hours=-4)))
            rth_close = _ET.localize(datetime.combine(day, _RTH_END)) if _ET else datetime.combine(day, _RTH_END).replace(tzinfo=timezone(timedelta(hours=-4)))
            window_start = max(s_et, rth_open)
            window_end = min(e_et, rth_close)
            if window_end > window_start:
                total_min += (window_end - window_start).total_seconds() / 60.0
        day = day + timedelta(days=1)
    return round(total_min, 2)


def effective_minutes_since(
    last_signal_ts: Optional[datetime],
    asset_class: Optional[str],
    now: Optional[datetime] = None,
) -> float:
    """Minutes since `last_signal_ts`, RTH-aware for equity/options bots.

    For RTH asset classes: returns market-hours-only minutes (Fri-pm to Mon-am
    becomes ~0 minutes since no RTH passes during weekends).
    For everything else (crypto / quant / futures / unknown): returns
    wall-clock minutes unchanged.
    """
    if last_signal_ts is None:
        return float("inf")
    now = now or datetime.now(timezone.utc)
    if last_signal_ts.tzinfo is None:
        last_signal_ts = last_signal_ts.replace(tzinfo=timezone.utc)
    ac = (asset_class or "").lower().strip()
    if ac in _RTH_CLASSES:
        return count_rth_minutes_between(last_signal_ts, now)
    # 24/7 asset — wall-clock
    return (now - last_signal_ts).total_seconds() / 60.0
