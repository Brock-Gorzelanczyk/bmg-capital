"""Monthly Rebalance strategy — fires on first Tuesday of each month."""
from __future__ import annotations

import calendar
import logging
from datetime import datetime, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "monthly_rebalance"


def _first_tuesday(year: int, month: int) -> int:
    """Return the day number of the first Tuesday in given year/month."""
    for day in range(1, 8):
        if calendar.weekday(year, month, day) == 1:  # 1 = Tuesday
            return day
    return -1


def _v1_signals(
    symbol: str,
    closes: list[float],
    timestamps: list[datetime],
) -> List[Signal]:
    """Return buy signal on first Tuesday of month within 30 min of market open.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last.
        timestamps: UTC bar timestamps, most-recent last.
    """
    if not timestamps or not closes:
        return []

    ts = timestamps[-1]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    # Convert to ET (UTC-5 standard, UTC-4 daylight — approximate with UTC-5)
    from datetime import timedelta
    et_ts = ts.astimezone(timezone(timedelta(hours=-5)))

    first_tue = _first_tuesday(et_ts.year, et_ts.month)
    is_rebalance_day = et_ts.day == first_tue

    # Within 30 minutes of 9:30 ET market open
    minutes_since_open = (et_ts.hour - 9) * 60 + (et_ts.minute - 30)
    near_open = 0 <= minutes_since_open <= 30

    if is_rebalance_day and near_open:
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=0.6,
            size_hint=0.6,
            reason=f"Monthly rebalance — first Tuesday {et_ts.strftime('%Y-%m-%d')}",
            strategy=STRATEGY_NAME,
        )]

    return []


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    """New-style interface called by runner.py."""
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list]
        timestamps_raw = [b.get("t") for b in bar_list]
        parsed_ts: list[datetime] = []
        for t in timestamps_raw:
            if isinstance(t, str):
                try:
                    parsed_ts.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
                except ValueError:
                    parsed_ts.append(datetime.now(timezone.utc))
            elif isinstance(t, datetime):
                parsed_ts.append(t)
            else:
                parsed_ts.append(datetime.now(timezone.utc))
        out.extend(_v1_signals(symbol, closes, parsed_ts))
    return out


def generate_signal(symbol: str, closes: list[float], timestamps: list[datetime]) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes, timestamps)
    return signals[0] if signals else None
