"""Crypto Session Open strategy — fade gap at 00:00 and 12:00 UTC opens."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "crypto_session_open"
GAP_THRESHOLD = 0.002  # 0.2% gap to trigger fade
SESSION_HOURS = {0, 12}  # UTC session open hours
SESSION_WINDOW_HOURS = 1  # bars within 1h of session open qualify


def _v1_signals(
    symbol: str,
    closes: list[float],
    opens: list[float],
    timestamps: list[datetime],
) -> List[Signal]:
    """Return fade signal within 1h of 00:00 or 12:00 UTC session open.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last.
        opens: Open prices, most-recent last.
        timestamps: UTC bar timestamps, most-recent last.
    """
    if not timestamps or len(closes) < 2 or len(opens) < 1:
        return []

    ts = timestamps[-1]
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    utc_ts = ts.astimezone(timezone.utc)

    # Check if within 1h of a session open
    in_window = False
    for session_hour in SESSION_HOURS:
        minutes_after = (utc_ts.hour - session_hour) * 60 + utc_ts.minute
        if 0 <= minutes_after < 60:
            in_window = True
            break

    if not in_window:
        return []

    gap = (opens[-1] - closes[-2]) / closes[-2] if closes[-2] != 0 else 0.0

    if gap > GAP_THRESHOLD:
        # Gapped up — fade with sell
        return [Signal(
            symbol=symbol,
            side="sell",
            confidence=0.5,
            size_hint=0.5,
            reason=(
                f"Crypto session fade sell: gap +{gap*100:.2f}% at "
                f"{utc_ts.strftime('%H:%M')} UTC"
            ),
            strategy=STRATEGY_NAME,
        )]

    if gap < -GAP_THRESHOLD:
        # Gapped down — fade with buy
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=0.5,
            size_hint=0.5,
            reason=(
                f"Crypto session fade buy: gap {gap*100:.2f}% at "
                f"{utc_ts.strftime('%H:%M')} UTC"
            ),
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
        opens = [float(b.get("o", 0)) for b in bar_list]
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
        out.extend(_v1_signals(symbol, closes, opens, parsed_ts))
    return out


def generate_signal(
    symbol: str,
    closes: list[float],
    opens: list[float],
    timestamps: list[datetime],
) -> Optional[Signal]:
    """Backwards-compat shim."""
    signals = _v1_signals(symbol, closes, opens, timestamps)
    return signals[0] if signals else None
