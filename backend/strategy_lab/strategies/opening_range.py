"""Opening Range Breakout strategy.

First 30 minutes of session defines the range.
Buy when price breaks above opening range high + 0.1%.
Used only for stock_day and crypto_day bots.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import List, Optional

import pytz

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)

STRATEGY_NAME = "opening_range"
OPENING_MINUTES = 30
BREAKOUT_BUFFER_PCT = 0.001  # 0.1%

ET = pytz.timezone("America/New_York")
_MARKET_OPEN = time(9, 30)
_RANGE_END = time(10, 0)  # 30 min after open


def _v1_signals(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    timestamps: list[datetime],
) -> List[Signal]:
    """Derive the opening range and return a Signal on breakout.

    Args:
        symbol: Ticker/pair symbol.
        closes: Close prices, most-recent last.
        highs: High prices, most-recent last.
        lows: Low prices, most-recent last.
        timestamps: UTC bar timestamps, most-recent last.
    """
    if not timestamps or len(closes) < 2:
        return []

    # Separate opening-range bars from post-open bars
    or_highs, or_lows = [], []
    for i, ts in enumerate(timestamps):
        et_ts = ts.astimezone(ET) if ts.tzinfo else ET.localize(ts)
        t = et_ts.time()
        if _MARKET_OPEN <= t < _RANGE_END:
            or_highs.append(highs[i])
            or_lows.append(lows[i])

    if not or_highs:
        return []

    range_high = max(or_highs)
    range_low = min(or_lows)
    buy_trigger = range_high * (1 + BREAKOUT_BUFFER_PCT)

    current_close = closes[-1]
    if current_close > buy_trigger:
        extension = (current_close - range_high) / range_high
        confidence = max(0.4, min(0.9, extension * 50))  # scale to reasonable range
        return [Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=(
                f"ORB buy: {current_close:.2f} > range high {range_high:.2f} + 0.1% "
                f"(range: {range_low:.2f}-{range_high:.2f})"
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
        closes     = [float(b.get("c", 0)) for b in bar_list]
        highs      = [float(b.get("h", 0)) for b in bar_list]
        lows       = [float(b.get("l", 0)) for b in bar_list]
        timestamps = [b.get("t") for b in bar_list]
        # Parse ISO string timestamps if needed
        parsed_ts: list[datetime] = []
        for t in timestamps:
            if isinstance(t, str):
                try:
                    parsed_ts.append(datetime.fromisoformat(t.replace("Z", "+00:00")))
                except ValueError:
                    parsed_ts.append(datetime.now(timezone.utc))
            elif isinstance(t, datetime):
                parsed_ts.append(t)
            else:
                parsed_ts.append(datetime.now(timezone.utc))
        out.extend(_v1_signals(symbol, closes, highs, lows, parsed_ts))
    return out


# Backwards-compat shim
def generate_signal(
    symbol: str,
    current_price: float,
    range_high: float,
    range_low: float,
    atr: float = 0.0,
) -> Optional[Signal]:
    """Single-value convenience wrapper (kept for backwards compatibility)."""
    if range_high <= range_low:
        return None
    buy_trigger = range_high * (1 + BREAKOUT_BUFFER_PCT)
    if current_price > buy_trigger:
        extension = (current_price - range_high) / range_high
        confidence = max(0.4, min(0.9, extension * 50))
        return Signal(
            symbol=symbol,
            side="buy",
            confidence=confidence,
            size_hint=confidence,
            reason=f"ORB buy: {current_price:.2f} > range high {range_high:.2f} + 0.1%",
            strategy=STRATEGY_NAME,
        )
    return None
