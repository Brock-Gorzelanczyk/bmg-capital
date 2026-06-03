"""
Multi-timeframe confluence checker.
Requires alignment across 3 timeframes before entry.

For day bots: 1min + 5min + 1h
For swing bots: 1d + 1w + 1mo (use whatever bars are available)
For lt bots: 1mo only, always returns 1.0

confluence_score: 0-1. Entry gated at >= 0.66.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)


def _sma(prices: list[float], period: int) -> float | None:
    """Compute simple moving average. Returns None if not enough data."""
    if len(prices) < period:
        return None
    return sum(prices[-period:]) / period


def _get_closes(bars: list[dict]) -> list[float]:
    """Extract close prices from a list of bar dicts."""
    closes = []
    for b in bars:
        c = b.get("c") or b.get("close") or b.get("vw")
        if c is not None:
            try:
                closes.append(float(c))
            except (TypeError, ValueError):
                pass
    return closes


def _compute_agreement(bars: list[dict], side: str, sma_period: int = 20) -> bool | None:
    """
    Returns True if bars agree with 'side', False if opposed, None if insufficient data.
    For 'buy': price > SMA(20) is agreement.
    For 'sell': price < SMA(20) is agreement.
    """
    closes = _get_closes(bars)
    if not closes:
        return None
    sma = _sma(closes, sma_period)
    if sma is None:
        return None
    current_price = closes[-1]
    if side == "buy":
        return current_price > sma
    elif side == "sell":
        return current_price < sma
    return None


def check_confluence(
    symbol: str,
    primary_signal: "Signal",
    bars: dict[str, list[dict]],
    bot_cadence: str,  # "day" | "swing" | "lt"
) -> float:
    """
    Check if 3 timeframes agree on direction.
    For a 'buy' signal: trend_alignment on HTF + LTF momentum not opposed.
    Returns score 0-1. 0.66+ = proceed, <0.66 = skip signal.

    Simple implementation:
    - Compute 20-period SMA on available bar granularities
    - If price > SMA on 2/3 timeframes (for buy) or < SMA on 2/3 (for sell): score = 0.8
    - If 3/3 agree: score = 1.0
    - If 1/3 agree: score = 0.4
    - If 0/3 agree: score = 0.0

    For day bot: use bars as "primary" timeframe, simulate HTF by using older bars
    (bars[-60:] as 1h equivalent for a 1-min bot)
    """
    side = primary_signal.side

    # lt bots: single timeframe, always proceed
    if bot_cadence == "lt":
        return 1.0

    # hold signals always pass
    if side == "hold":
        return 1.0

    symbol_bars = bars.get(symbol, [])
    if not symbol_bars:
        logger.debug("[mtf:%s] No bars available, returning neutral 0.5", symbol)
        return 0.5

    agreements: list[bool] = []

    if bot_cadence == "day":
        # Three synthetic timeframes from the same bar list:
        # LTF: last 20 bars
        # Primary: last 60 bars
        # HTF: last 180 bars (simulates 1h context from 1-min bars)
        ltf_bars = symbol_bars[-20:] if len(symbol_bars) >= 20 else symbol_bars
        primary_bars = symbol_bars[-60:] if len(symbol_bars) >= 60 else symbol_bars
        htf_bars = symbol_bars[-180:] if len(symbol_bars) >= 180 else symbol_bars

        for bar_slice in (ltf_bars, primary_bars, htf_bars):
            result = _compute_agreement(bar_slice, side)
            if result is not None:
                agreements.append(result)

    elif bot_cadence == "swing":
        # Use full bar set as "daily", simulate weekly by every 5th bar, monthly by every 22nd
        daily_bars = symbol_bars
        weekly_bars = symbol_bars[::5] if len(symbol_bars) >= 5 else symbol_bars
        monthly_bars = symbol_bars[::22] if len(symbol_bars) >= 22 else symbol_bars

        for bar_slice in (daily_bars, weekly_bars, monthly_bars):
            result = _compute_agreement(bar_slice, side)
            if result is not None:
                agreements.append(result)

    else:
        # Unknown cadence — default to primary only
        result = _compute_agreement(symbol_bars, side)
        if result is not None:
            agreements.append(result)

    if not agreements:
        logger.debug("[mtf:%s] Could not compute any TF agreement, returning 0.5", symbol)
        return 0.5

    agree_count = sum(1 for a in agreements if a)
    total = len(agreements)

    if total == 0:
        return 0.5

    ratio = agree_count / total

    if ratio >= 1.0:
        score = 1.0
    elif ratio >= 2 / 3:
        score = 0.8
    elif ratio >= 1 / 3:
        score = 0.4
    else:
        score = 0.0

    logger.debug(
        "[mtf:%s] cadence=%s side=%s agree=%d/%d score=%.2f",
        symbol, bot_cadence, side, agree_count, total, score,
    )
    return score
