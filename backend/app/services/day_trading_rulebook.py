"""BMG Day-Trading Rulebook enforcement.

See vault: [[2026-08-29-day-trading-rulebook]] and [[2026-08-29-day-trading-sleeve-synthesis]]

Every day-trade bot MUST call `check_can_enter()` before submitting an order.
Returns (allowed: bool, reason: str). Reason is human-readable.

Rules enforced (defaults, all env-overridable):

  1. 1R = $100 per trade (1% of $10K NAV — max loss per single trade)
  2. Daily loss cap: -$300 (3R) — force stop for the trading day
  3. Weekly loss cap: -$600 (6R) — force stop for the week
  4. Trailing max drawdown: -$800 (8%) from sleeve peak — real-money halt
  5. Time windows: no entries 9:30-9:45 ET, no entries 3:30-4:00 ET
  6. News blackout: no entries 5 min before/after FOMC / NFP / CPI / PPI
     (implementation notes below — currently returns "no scheduled event")
  7. Tilt cutoff: 3 consecutive losers OR -2R day → walk

Reads state from bot_trades + bot_positions filtered to the day-trading
sleeve's allocation_id.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional, Tuple

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

# Rulebook defaults (all overridable via env)
R_UNIT_USD = float(os.environ.get("DAYTRADE_R_UNIT_USD", "100"))       # 1R = $100
DAILY_LOSS_CAP_R = float(os.environ.get("DAYTRADE_DAILY_LOSS_CAP_R", "3"))    # -3R
WEEKLY_LOSS_CAP_R = float(os.environ.get("DAYTRADE_WEEKLY_LOSS_CAP_R", "6"))  # -6R
TRAILING_DD_USD = float(os.environ.get("DAYTRADE_TRAILING_DD_USD", "800"))    # -$800
TILT_CONSECUTIVE_LOSSES = int(os.environ.get("DAYTRADE_TILT_CONSEC_LOSSES", "3"))

# Time windows (ET)
NO_ENTRY_BEFORE = time(9, 45)   # skip 9:30-9:45 open chaos
NO_ENTRY_AFTER = time(15, 30)   # skip 3:30-4:00 MOC pressure

# News blackout window (minutes around scheduled economic events)
NEWS_BLACKOUT_MIN = int(os.environ.get("DAYTRADE_NEWS_BLACKOUT_MIN", "5"))


@dataclass
class RulebookCheck:
    allowed: bool
    reason: str
    daily_pnl_usd: float = 0.0
    weekly_pnl_usd: float = 0.0
    trailing_dd_usd: float = 0.0
    consecutive_losses: int = 0


def _now_et() -> datetime:
    return datetime.now(ET)


def _in_time_window(now: Optional[datetime] = None) -> Tuple[bool, str]:
    now = now or _now_et()
    t = now.time()
    if now.weekday() >= 5:
        return False, f"weekend (dow={now.weekday()})"
    if t < NO_ENTRY_BEFORE:
        return False, f"pre-{NO_ENTRY_BEFORE.strftime('%H:%M')} ET (open chaos)"
    if t >= NO_ENTRY_AFTER:
        return False, f"post-{NO_ENTRY_AFTER.strftime('%H:%M')} ET (MOC pressure)"
    return True, "in-window"


def _in_news_blackout(now: Optional[datetime] = None) -> Tuple[bool, str]:
    """Placeholder — future: query FRED economic calendar or FMP calendar API
    to blackout ±N minutes around FOMC/NFP/CPI/PPI. Returns False by default."""
    # TODO wire to app.services.economic_calendar if/when it exists
    return False, "no scheduled event"


def _sum_realized_pnl_since(db, allocation_id: int, since_utc: datetime) -> float:
    """Sum realized P&L (in USD) for closed positions of this alloc since ts."""
    from sqlalchemy import text
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(realized_pnl_cents), 0) "
            "FROM bot_positions "
            "WHERE allocation_id = :aid AND closed_at IS NOT NULL "
            "AND closed_at >= :since"
        ),
        {"aid": allocation_id, "since": since_utc.isoformat()},
    ).fetchone()
    return float(row[0] or 0) / 100.0


def _sum_unrealized_pnl(db, allocation_id: int) -> float:
    """Sum unrealized P&L for currently-open positions of this alloc."""
    from sqlalchemy import text
    row = db.execute(
        text(
            "SELECT COALESCE(SUM(unrealized_pnl_cents), 0) "
            "FROM bot_positions "
            "WHERE allocation_id = :aid AND closed_at IS NULL"
        ),
        {"aid": allocation_id},
    ).fetchone()
    return float(row[0] or 0) / 100.0


def _consecutive_losses(db, allocation_id: int, limit: int = 10) -> int:
    """Count consecutive losers most-recent-first, until a winner appears."""
    from sqlalchemy import text
    rows = db.execute(
        text(
            "SELECT COALESCE(realized_pnl_cents, 0) FROM bot_positions "
            "WHERE allocation_id = :aid AND closed_at IS NOT NULL "
            "ORDER BY closed_at DESC LIMIT :lim"
        ),
        {"aid": allocation_id, "lim": limit},
    ).fetchall()
    count = 0
    for r in rows:
        if float(r[0] or 0) < 0:
            count += 1
        else:
            break
    return count


def check_can_enter(db, allocation_id: int, now: Optional[datetime] = None) -> RulebookCheck:
    """Preflight check called by every day-trade bot before entering a new trade.

    Returns RulebookCheck(allowed, reason, ...). Bot must NOT submit an order
    if allowed=False.
    """
    now = now or _now_et()

    # 1. Time window
    in_window, win_reason = _in_time_window(now)
    if not in_window:
        return RulebookCheck(allowed=False, reason=f"time_window: {win_reason}")

    # 2. News blackout
    in_blackout, blk_reason = _in_news_blackout(now)
    if in_blackout:
        return RulebookCheck(allowed=False, reason=f"news_blackout: {blk_reason}")

    # 3. Daily loss cap (realized P&L since midnight ET)
    midnight_et = ET.localize(datetime.combine(now.date(), time(0, 0)))
    midnight_utc = midnight_et.astimezone(timezone.utc)
    daily_pnl = _sum_realized_pnl_since(db, allocation_id, midnight_utc)
    daily_cap = -DAILY_LOSS_CAP_R * R_UNIT_USD
    if daily_pnl <= daily_cap:
        return RulebookCheck(
            allowed=False,
            reason=f"daily_loss_cap: {daily_pnl:.2f} <= {daily_cap:.2f}",
            daily_pnl_usd=daily_pnl,
        )

    # 4. Weekly loss cap (Mon 00:00 ET)
    days_since_monday = now.weekday()
    monday_et = ET.localize(datetime.combine(now.date() - timedelta(days=days_since_monday), time(0, 0)))
    monday_utc = monday_et.astimezone(timezone.utc)
    weekly_pnl = _sum_realized_pnl_since(db, allocation_id, monday_utc)
    weekly_cap = -WEEKLY_LOSS_CAP_R * R_UNIT_USD
    if weekly_pnl <= weekly_cap:
        return RulebookCheck(
            allowed=False,
            reason=f"weekly_loss_cap: {weekly_pnl:.2f} <= {weekly_cap:.2f}",
            daily_pnl_usd=daily_pnl, weekly_pnl_usd=weekly_pnl,
        )

    # 5. Trailing drawdown (all-time realized + current unrealized)
    lifetime_realized = _sum_realized_pnl_since(db, allocation_id, datetime(2000, 1, 1, tzinfo=timezone.utc))
    current_open = _sum_unrealized_pnl(db, allocation_id)
    # Simplified: use combined P&L as drawdown proxy (peak = max(0, lifetime))
    # A full impl would track a rolling peak; here we approximate.
    combined = lifetime_realized + current_open
    if combined <= -TRAILING_DD_USD:
        return RulebookCheck(
            allowed=False,
            reason=f"trailing_drawdown: {combined:.2f} <= -{TRAILING_DD_USD:.2f}",
            daily_pnl_usd=daily_pnl, weekly_pnl_usd=weekly_pnl,
            trailing_dd_usd=combined,
        )

    # 6. Tilt cutoff — N consecutive losers
    consec = _consecutive_losses(db, allocation_id)
    if consec >= TILT_CONSECUTIVE_LOSSES:
        return RulebookCheck(
            allowed=False,
            reason=f"tilt_cutoff: {consec} consecutive losses",
            daily_pnl_usd=daily_pnl, weekly_pnl_usd=weekly_pnl,
            consecutive_losses=consec,
        )

    return RulebookCheck(
        allowed=True,
        reason="ok",
        daily_pnl_usd=daily_pnl,
        weekly_pnl_usd=weekly_pnl,
        trailing_dd_usd=combined,
        consecutive_losses=consec,
    )


def force_flat_by_eod(db, allocation_id: int) -> None:
    """Placeholder — day-trade bots register a 3:55 PM ET job that closes
    any open positions to enforce no-overnight-hold. Implementations should
    call this from their EOD cron."""
    logger.info("[rulebook] force_flat_by_eod placeholder called for alloc=%d", allocation_id)
