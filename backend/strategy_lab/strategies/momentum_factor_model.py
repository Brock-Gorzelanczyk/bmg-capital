"""Momentum Factor Model — cross-sectional 12-1 momentum, monthly rebalance.

Thesis: Classic Fama-French / AQR-style factor. Rank watchlist by
"12-month minus 1-month" total return (the 12-1 momentum signal:
strongest 11-month trend with the short-term reversal subtracted).
Long the top decile, short the bottom decile, hold for a month.

Unlike every other strategy, this one is CROSS-SECTIONAL — it consumes
the full bars dict at once, computes scores across all symbols, ranks,
and emits a BATCH of 10+ signals (or zero). It does NOT iterate
per-symbol independently.

Cadence: Fires only on the first trading day of each calendar month.
"First trading day" detected from the bar history itself: if the most
recent bar's date is the ONLY bar from that calendar month in our
lookback, today is the first trading day.

Regime: bull_trending (momentum factor pays best in trends).
Active hours: any (designed for daily-cadence stock_lt).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone, date
from typing import Any, List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "momentum_factor_model"

_ET_OFFSET = timezone(timedelta(hours=-4))  # EDT
MIN_DAILY_BARS = 252           # need 12 months of daily history per symbol
LOOKBACK_TOTAL = 252           # 12-month return endpoint
LOOKBACK_REVERSAL = 21         # subtract last 1-month return
DECILE_FRACTION = 0.10         # 10% top + 10% bottom
SIZE_HINT = 0.02               # small per position — we emit up to ~20 signals
MAX_CONFIDENCE = 0.85


def _bar_date(b: dict) -> Optional[date]:
    ts = b.get("ts")
    if not ts:
        return None
    try:
        s = str(ts)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(_ET_OFFSET).date()
    except Exception:
        return None


def _is_first_trading_day(bar_list: list) -> bool:
    """Is the most recent bar the only bar from its calendar month in our lookback?"""
    if not bar_list:
        return False
    most_recent = _bar_date(bar_list[-1])
    if most_recent is None:
        return False
    # Count bars whose ET date is in the same (year, month) as the most recent
    same_month = 0
    for b in bar_list[-25:]:  # only look at recent 25 bars — sufficient since a month has <= 23 trading days
        d = _bar_date(b)
        if d is not None and d.year == most_recent.year and d.month == most_recent.month:
            same_month += 1
    return same_month == 1


def _momentum_score(closes: list[float]) -> Optional[float]:
    """12-1 momentum: ((p_today / p_252d_ago) - 1) - ((p_today / p_21d_ago) - 1)."""
    if len(closes) < MIN_DAILY_BARS:
        return None
    p_today = closes[-1]
    p_lookback = closes[-LOOKBACK_TOTAL]
    p_reversal = closes[-LOOKBACK_REVERSAL]
    if p_lookback <= 0 or p_reversal <= 0 or p_today <= 0:
        return None
    r_12m = (p_today / p_lookback) - 1.0
    r_1m = (p_today / p_reversal) - 1.0
    return r_12m - r_1m


def _spy_direction(bars: dict) -> Optional[int]:
    spy = bars.get("SPY") or bars.get("SPY/USD")
    if not spy or len(spy) < LOOKBACK_REVERSAL + 1:
        return None
    try:
        c_now = float(spy[-1].get("c", 0))
        c_21_ago = float(spy[-LOOKBACK_REVERSAL].get("c", 0))
        if c_now <= 0 or c_21_ago <= 0:
            return None
        return 1 if c_now > c_21_ago else -1 if c_now < c_21_ago else 0
    except Exception:
        return None


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    if not bars:
        return []

    # Use the first symbol's bars to determine "first trading day of month"
    # All symbols share the same fetch date; checking one is sufficient.
    sample_bars = next(iter(bars.values()), None)
    if not sample_bars or not _is_first_trading_day(sample_bars):
        return []

    rebalance_date = _bar_date(sample_bars[-1])
    rebalance_iso = rebalance_date.isoformat() if rebalance_date else None

    # Compute momentum score per symbol
    scored: list[tuple[str, float]] = []
    for symbol, bar_list in bars.items():
        if symbol in ("SPY", "SPY/USD"):
            continue  # SPY is the benchmark, not a candidate
        try:
            closes = [float(b.get("c", 0) or 0) for b in bar_list]
            score = _momentum_score(closes)
            if score is None:
                continue
            scored.append((symbol, score))
        except Exception as exc:
            logger.warning("[%s] %s scoring failed: %s", STRATEGY_NAME, symbol, exc)

    n = len(scored)
    if n < 10:
        logger.warning("[%s] only %d ranked symbols — need ≥ 10 to decile-split", STRATEGY_NAME, n)
        return []

    scored.sort(key=lambda x: x[1], reverse=True)
    decile_size = max(1, int(round(n * DECILE_FRACTION)))
    longs = scored[:decile_size]
    shorts = scored[-decile_size:]

    spy_dir = _spy_direction(bars)
    out: List[Signal] = []

    for rank, (sym, score) in enumerate(longs, start=1):
        cross_agree = (spy_dir == 1) if spy_dir is not None else False
        reason_payload = {
            "setup": "momentum_factor_model",
            "side": "long",
            "rebalance_date": rebalance_iso,
            "momentum_score": round(score, 4),
            "rank": rank,
            "watchlist_size": n,
            "volume_agreement": 0.5,
            "mtf_alignment": 0.5,
            "cross_asset_agree": cross_agree,
        }
        out.append(Signal(
            symbol=sym,
            side="buy",
            confidence=min(MAX_CONFIDENCE, 0.65 + 0.10 * (1.0 - rank / decile_size)),
            size_hint=SIZE_HINT,
            strategy=STRATEGY_NAME,
            reason=json.dumps(reason_payload),
        ))

    for rank_offset, (sym, score) in enumerate(reversed(shorts), start=1):
        rank = n - rank_offset + 1
        cross_agree = (spy_dir == -1) if spy_dir is not None else False
        reason_payload = {
            "setup": "momentum_factor_model",
            "side": "short",
            "rebalance_date": rebalance_iso,
            "momentum_score": round(score, 4),
            "rank": rank,
            "watchlist_size": n,
            "volume_agreement": 0.5,
            "mtf_alignment": 0.5,
            "cross_asset_agree": cross_agree,
        }
        out.append(Signal(
            symbol=sym,
            side="sell",
            confidence=min(MAX_CONFIDENCE, 0.65 + 0.10 * (1.0 - rank_offset / decile_size)),
            size_hint=SIZE_HINT,
            strategy=STRATEGY_NAME,
            reason=json.dumps(reason_payload),
        ))

    logger.info("[%s] rebalance fired: %d long + %d short across %d ranked symbols",
                STRATEGY_NAME, len(longs), len(shorts), n)
    return out
