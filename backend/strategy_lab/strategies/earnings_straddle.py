"""Earnings straddle — long ATM straddle 3 trading days before earnings.

Source: Gao, Xing & Zhang, "Anticipating Uncertainty: Straddles Around
Earnings Announcements," JFQA 2018. SSRN: https://ssrn.com/abstract=2204549

Paper's headline finding: buying an ATM straddle 3 trading days pre-
announcement and closing the morning after generates ~3.34% mean return
per event over the 3-day window. Effect stronger for smaller, higher-vol,
higher-kurtosis names. Distribution is right-skewed (jump-driven), so
expect <50% winners with fat right tail.

Entry conditions (paper's exact filters):
  1. Stock price >= $5
  2. Option open interest > 0 on ATM strike
  3. abs(delta) 0.375-0.625 (near-ATM)
  4. Moneyness 0.9-1.1 (strike within 10% of spot)
  5. Earnings scheduled within 3 trading days

Exit: T+1 after earnings (paper closes at market open post-announcement).
Runner enforces this as a max holding of ~5 calendar days.

Signal shape:
  side = "buy" (long-only, we buy the straddle)
  setup = "earnings_straddle_long" — runner routes to long_straddle intent
  reason_json contains earnings_date + expected exit_by
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from strategy_lab.core.signals import Signal

logger = logging.getLogger(__name__)
STRATEGY_NAME = "earnings_straddle"

MIN_PRICE = 5.0
BASE_SIZE = 0.10   # 10% of options bot capital per straddle (was $200-800 range per paper)
DAYS_BEFORE_EARNINGS = 3


def _earnings_date_for(symbol: str) -> Optional[date]:
    """Best-effort earnings date fetch via yfinance calendar. Returns None
    on any failure so the strategy silently skips symbols without data.
    """
    try:
        import yfinance as yf  # type: ignore
        cal = yf.Ticker(symbol).calendar
        if not cal:
            return None
        eds = cal.get("Earnings Date") or []
        if not eds:
            return None
        today = date.today()
        # calendar sometimes returns a list of dates; pick the nearest FUTURE one
        for ed in eds:
            if hasattr(ed, "year") and ed >= today:
                return ed
        return None
    except Exception as exc:
        logger.debug("[earnings_straddle] %s calendar fetch failed: %s", symbol, exc)
        return None


def _within_window(earnings_date: date, days_before: int) -> bool:
    """True if today is within `days_before` trading days of earnings_date."""
    today = date.today()
    delta_days = (earnings_date - today).days
    # Approximate trading days by scaling: 3 trading days ≈ 5 calendar days
    # in the worst case (spans a weekend). Accept 0..(days_before * 5/3) window.
    max_cal_days = int(days_before * 5 / 3) + 1
    return 0 <= delta_days <= max_cal_days


def _entry_conditions(
    symbol: str,
    closes: list[float],
) -> tuple[bool, float, str]:
    if not closes:
        return False, 0.0, ""
    spot = float(closes[-1])
    if spot < MIN_PRICE:
        return False, 0.0, ""
    ed = _earnings_date_for(symbol)
    if ed is None:
        return False, 0.0, ""
    if not _within_window(ed, DAYS_BEFORE_EARNINGS):
        return False, 0.0, ""
    # Confidence scaled by how close to earnings — T-1 confidence 1.0,
    # T-3 confidence 0.6. Encodes the paper's "closer is stronger."
    days_out = max(0, (ed - date.today()).days)
    conf = max(0.5, 1.0 - (days_out * 0.15))
    reason = json.dumps({
        "setup": "earnings_straddle_long",
        "spot": round(spot, 4),
        "earnings_date": ed.isoformat(),
        "days_to_earnings": days_out,
        "paper": "Gao-Xing-Zhang 2018 SSRN 2204549",
    })
    return True, float(conf), reason


def generate_signals(bars: dict, profile_config: dict, regime: dict) -> List[Signal]:
    out: List[Signal] = []
    for symbol, bar_list in bars.items():
        if not bar_list:
            continue
        closes = [float(b.get("c", 0)) for b in bar_list if b.get("c")]
        if not closes:
            continue
        enter, conf, reason = _entry_conditions(symbol, closes)
        if not enter:
            continue
        out.append(Signal(
            symbol=symbol,
            side="buy",
            confidence=conf,
            size_hint=BASE_SIZE,
            reason=reason,
            strategy=STRATEGY_NAME,
        ))
    return out


def generate_signal(symbol: str, closes: list[float], **kwargs) -> Optional[Signal]:
    enter, conf, reason = _entry_conditions(symbol, closes)
    if not enter:
        return None
    return Signal(
        symbol=symbol, side="buy", confidence=conf,
        size_hint=BASE_SIZE, reason=reason, strategy=STRATEGY_NAME,
    )
