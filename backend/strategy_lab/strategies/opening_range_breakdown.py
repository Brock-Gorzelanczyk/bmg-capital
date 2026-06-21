"""Opening Range Breakdown — break of 9:30-10:00 ET range with volume.

Thesis: The first 30 minutes of a trading session set the day's
opening range (OR). A confirmed break of OR_low (with above-average
volume) often signals continuation lower; a symmetric break above OR_high
signals continuation higher.

Regime: any (trades best on trending days; the discipline filter's
confluence gate will dampen choppy days via volatility_regime factor).

Active hours: 10:00–15:00 ET (must wait for OR to close, exit before
last hour). Bot owner is `stock_day` which has 5m bars on cadence
`*/5 4-19 * * 1-5`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

_ET_OFFSET = timezone(timedelta(hours=-4))  # EDT (June). EST (-5h) for Nov-Mar.
from typing import List

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "opening_range_breakdown"

MIN_BARS = 60                      # need OR + 20 avg-vol + recent context
VOLUME_MULTIPLE_REQUIRED = 1.5     # break candle vol must exceed 1.5× recent avg
MAX_CONFIDENCE = 0.80


def _to_et(ts_raw) -> datetime | None:
    """Parse the bar's ts (ISO string from runner) and return ET-local datetime.

    Bars are emitted by the runner as ISO strings (usually UTC). We do a fixed
    -4h EDT shift — close enough for date/hour binning in summer.
    """
    if not ts_raw:
        return None
    try:
        s = str(ts_raw)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        # Convert to ET (EDT, -4h) and strip tz for simple hour/minute comparisons.
        return dt.astimezone(_ET_OFFSET).replace(tzinfo=None)
    except Exception:
        return None


def _et_hour_now() -> int:
    return (datetime.now(timezone.utc).hour - 4) % 24


def _opening_range(bars_today: list, et_times: list[datetime]) -> tuple[float, float, float, int] | None:
    """Return (or_high, or_low, or_avg_vol, n_or_bars) for the 9:30-10:00 ET window."""
    or_highs: list[float] = []
    or_lows: list[float] = []
    or_vols: list[float] = []
    for bar, et in zip(bars_today, et_times):
        if et is None:
            continue
        minutes = et.hour * 60 + et.minute
        # 9:30 ET = 570 min, 10:00 ET = 600 min
        if 570 <= minutes < 600:
            or_highs.append(float(bar.get("h", 0) or 0))
            or_lows.append(float(bar.get("l", 0) or 0))
            or_vols.append(float(bar.get("v", 0) or 0))
    if not or_highs or not or_lows:
        return None
    or_h = max(or_highs)
    or_l = min(or_lows)
    or_v = (sum(or_vols) / len(or_vols)) if or_vols else 0.0
    if or_h <= 0 or or_l <= 0 or or_h <= or_l:
        return None
    return or_h, or_l, or_v, len(or_highs)


def _build_signal_for_symbol(symbol: str, bar_list: list) -> Signal | None:
    if not bar_list or len(bar_list) < MIN_BARS:
        return None

    # Parse ET times for all bars
    et_times = [_to_et(b.get("ts")) for b in bar_list]

    # Last bar — used to pin "today"
    last_et = et_times[-1]
    if last_et is None:
        return None
    today = last_et.date()

    # Filter to today's bars only
    today_bars: list = []
    today_et: list[datetime] = []
    for b, et in zip(bar_list, et_times):
        if et is not None and et.date() == today:
            today_bars.append(b)
            today_et.append(et)

    if len(today_bars) < 7:  # need OR (6 bars at 5m) + at least one post-OR bar
        return None

    or_data = _opening_range(today_bars, today_et)
    if or_data is None:
        return None
    or_high, or_low, or_avg_vol, n_or_bars = or_data

    # The breakout candle = the most recent today bar after 10:00 ET
    last_minutes = last_et.hour * 60 + last_et.minute
    if last_minutes < 600:  # before 10:00 ET → OR still forming, no signal
        return None
    if last_minutes >= 900:  # after 15:00 ET → close-of-day, no new entries
        return None

    last_bar = today_bars[-1]
    last_c = float(last_bar.get("c", 0) or 0)
    last_v = float(last_bar.get("v", 0) or 0)
    if last_c <= 0:
        return None

    # Recent average volume (last 20 bars before the most-recent one) for the multiple check
    recent_vols = [float(b.get("v", 0) or 0) for b in bar_list[-21:-1]]
    avg_vol = (sum(recent_vols) / len(recent_vols)) if recent_vols else 0.0
    if avg_vol <= 0:
        avg_vol = or_avg_vol  # fall back to OR avg if no recent vol
    if avg_vol <= 0:
        return None

    vol_multiple = last_v / avg_vol
    or_range = or_high - or_low

    # LONG breakout
    if last_c > or_high and vol_multiple >= VOLUME_MULTIPLE_REQUIRED:
        ext_excess = (last_c - or_high) / or_range
        confidence = min(MAX_CONFIDENCE, 0.55 + 0.12 * (vol_multiple - VOLUME_MULTIPLE_REQUIRED) + 0.10 * ext_excess)
        return Signal(
            symbol=symbol,
            side="buy",
            confidence=round(confidence, 3),
            size_hint=0.05,
            strategy=STRATEGY_NAME,
            reason=(
                f'{{"setup":"orb_long","or_high":{or_high:.2f},"or_low":{or_low:.2f},'
                f'"vol_multiple":{vol_multiple:.2f},"or_bars":{n_or_bars},'
                f'"volume_agreement":{min(1.0, vol_multiple / 3.0):.2f},'
                f'"mtf_alignment":0.55,"cross_asset_agree":false}}'
            ),
        )

    # SHORT breakdown (will be filtered by long_only bots — emit for completeness)
    if last_c < or_low and vol_multiple >= VOLUME_MULTIPLE_REQUIRED:
        ext_excess = (or_low - last_c) / or_range
        confidence = min(MAX_CONFIDENCE, 0.55 + 0.12 * (vol_multiple - VOLUME_MULTIPLE_REQUIRED) + 0.10 * ext_excess)
        return Signal(
            symbol=symbol,
            side="sell",
            confidence=round(confidence, 3),
            size_hint=0.05,
            strategy=STRATEGY_NAME,
            reason=(
                f'{{"setup":"orb_short","or_high":{or_high:.2f},"or_low":{or_low:.2f},'
                f'"vol_multiple":{vol_multiple:.2f},"or_bars":{n_or_bars},'
                f'"volume_agreement":{min(1.0, vol_multiple / 3.0):.2f},'
                f'"mtf_alignment":0.55,"cross_asset_agree":false}}'
            ),
        )

    return None


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """Opening-range break with volume confirmation."""
    if not bars:
        return []

    h_et = _et_hour_now()
    # Hard active-hours guard — OR isn't complete before 10:00 ET
    if not (10 <= h_et < 15):
        return []

    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        try:
            sig = _build_signal_for_symbol(symbol, bar_list)
            if sig is not None:
                out.append(sig)
        except Exception as exc:
            logger.warning("[%s] %s failed: %s", STRATEGY_NAME, symbol, exc)
    return out
