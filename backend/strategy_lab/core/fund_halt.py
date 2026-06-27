"""Fund-level halt — peak-to-current drawdown gate.

Standing decision (vault context/06-decision-history.md):
  -1.5% NAV from peak  -> pause new allocations (this gate)
  -3.0% NAV from peak  -> unwind to 30% leverage (separate flow)

This module implements ONLY the pre-trade pause gate. It does NOT flatten
or modify existing positions. It is called from _execute_signal before any
new BotPosition is created. When the drawdown threshold is breached, the
caller is expected to skip execution and persist a hold signal with the
returned reason.

Drawdown formula:
    drawdown_pct = (current_pv - peak_pv) / peak_pv * 100

Peak source:
    Rolling 90d max of SUM(bot_daily_pnl.portfolio_value_eod_cents) per date
    across all allocations owned by user_id. Falls back to current canonical
    portfolio_value_cents (peak == current, drawdown == 0) when the daily
    table is empty or unreadable -> safe-default allowed.

Env overrides:
    FUND_HALT_PAUSE_PCT   (default -1.5)   pause new entries below this
    FUND_HALT_UNWIND_PCT  (default -3.0)   informational only here

Returns:
    (allowed: bool, reason: str)
    reason == "" when allowed.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_PEAK_LOOKBACK_DAYS = 90


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("[fund-halt] invalid %s=%r, using default %s", name, raw, default)
        return default


def _current_portfolio_value_cents(db, user_id: int) -> Optional[int]:
    """Pull canonical current PV. None on any error -> safe default."""
    try:
        from app.core.canonical import get_canonical_portfolio_state
        state = get_canonical_portfolio_state(user_id, db) or {}
        pv = state.get("portfolio_value_cents")
        if pv is None:
            return None
        return int(pv)
    except Exception as exc:
        logger.warning("[fund-halt] canonical PV fetch failed: %s", exc)
        return None


def _rolling_peak_cents(db, user_id: int, current_pv_cents: int) -> int:
    """Max of daily SUM(portfolio_value_eod_cents) across user's allocations
    within the rolling lookback window. Always >= current_pv_cents so the
    drawdown denominator is never zero and never smaller than today's PV.
    """
    try:
        from app.db.models.bots import BotDailyPnL, BotAllocation
        from sqlalchemy import func

        cutoff = date.today() - timedelta(days=_PEAK_LOOKBACK_DAYS)
        # SUM(portfolio_value_eod_cents) per date, joined to allocations
        # owned by this user. Take the max across dates.
        rows = (
            db.query(
                BotDailyPnL.date,
                func.sum(BotDailyPnL.portfolio_value_eod_cents).label("pv_sum"),
            )
            .join(BotAllocation, BotAllocation.id == BotDailyPnL.allocation_id)
            .filter(BotAllocation.user_id == user_id)
            .filter(BotDailyPnL.date >= cutoff)
            .filter(BotDailyPnL.portfolio_value_eod_cents.isnot(None))
            .group_by(BotDailyPnL.date)
            .all()
        )
        if not rows:
            logger.info(
                "[fund-halt] no bot_daily_pnl rows in last %dd for user_id=%d — using current PV as peak",
                _PEAK_LOOKBACK_DAYS, user_id,
            )
            return current_pv_cents
        peak = max(int(r.pv_sum or 0) for r in rows)
        return max(peak, current_pv_cents)
    except Exception as exc:
        logger.warning("[fund-halt] peak query failed: %s — using current PV as peak", exc)
        return current_pv_cents


def compute_drawdown(db, user_id: int) -> dict:
    """Return a structured diagnostic for the fund-halt state.

    Shape:
        {
          "user_id": int,
          "current_pv_cents": int,
          "peak_pv_cents": int,
          "drawdown_pct": float,         # negative when under peak
          "pause_threshold_pct": float,
          "unwind_threshold_pct": float,
          "halted": bool,
          "would_unwind": bool,
          "reason": str,
        }
    """
    pause_pct = _env_float("FUND_HALT_PAUSE_PCT", -1.5)
    unwind_pct = _env_float("FUND_HALT_UNWIND_PCT", -3.0)

    current = _current_portfolio_value_cents(db, user_id)
    if current is None or current <= 0:
        return {
            "user_id": user_id,
            "current_pv_cents": current or 0,
            "peak_pv_cents": current or 0,
            "drawdown_pct": 0.0,
            "pause_threshold_pct": pause_pct,
            "unwind_threshold_pct": unwind_pct,
            "halted": False,
            "would_unwind": False,
            "reason": "no_canonical_pv",
        }

    peak = _rolling_peak_cents(db, user_id, current)
    if peak <= 0:
        return {
            "user_id": user_id,
            "current_pv_cents": current,
            "peak_pv_cents": peak,
            "drawdown_pct": 0.0,
            "pause_threshold_pct": pause_pct,
            "unwind_threshold_pct": unwind_pct,
            "halted": False,
            "would_unwind": False,
            "reason": "zero_peak",
        }

    drawdown_pct = round((current - peak) / peak * 100.0, 4)
    halted = drawdown_pct <= pause_pct
    would_unwind = drawdown_pct <= unwind_pct

    if halted:
        reason = (
            "dd={dd:.2f}% <= pause {p:.2f}% (peak={peak} current={cur})"
            .format(dd=drawdown_pct, p=pause_pct, peak=peak, cur=current)
        )
    else:
        reason = ""

    return {
        "user_id": user_id,
        "current_pv_cents": current,
        "peak_pv_cents": peak,
        "drawdown_pct": drawdown_pct,
        "pause_threshold_pct": pause_pct,
        "unwind_threshold_pct": unwind_pct,
        "halted": halted,
        "would_unwind": would_unwind,
        "reason": reason,
    }


def check_fund_halt(db, user_id: int) -> Tuple[bool, str]:
    """Returns (allowed, reason). reason="" when allowed.

    Computes fund peak-to-current drawdown from canonical state.
    Peak = max(portfolio_value_cents) over rolling 90d window (or all-time
    if shorter history). Current = canonical portfolio_value_cents now.

    Drawdown = (current - peak) / peak.

    Env overrides:
        FUND_HALT_PAUSE_PCT  (default -1.5)
        FUND_HALT_UNWIND_PCT (default -3.0)

    Safe default: if anything in the calculation fails (missing tables,
    no canonical PV, query errors), this function returns (True, "")
    so trading is never halted by a diagnostic failure. The accompanying
    log line will say so.
    """
    try:
        diag = compute_drawdown(db, user_id)
    except Exception as exc:
        logger.warning("[fund-halt] compute_drawdown raised %s — safe-default allow", exc)
        return True, ""

    if diag.get("halted"):
        return False, diag.get("reason", "fund_drawdown_breach")
    return True, ""
