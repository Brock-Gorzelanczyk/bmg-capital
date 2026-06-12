"""
Strategy Monitor Agent — tracks BMG Capital app and bot execution health.

Checks every morning (called by Queen at 7 AM ET):
  1. Bot execution windows — last signal vs expected run interval
  2. Alpaca paper account connectivity and equity snapshot
  3. Signal generation rate vs 7-day baseline
  4. Dead-bot detection (bots that should have run but haven't)

Returns a health dict consumed by the Queen Agent.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Max hours between signals before a bot is considered stale.
# Thresholds are generous — alert fires at 2× the normal interval.
_EXPECTED_INTERVAL_HOURS: dict[str, float] = {
    "stock_swing":                 24,    # once post-close
    "stock_day":                   1,     # every 5 min during market hours
    "stock_lt":                    168,   # weekly
    "crypto_swing":                8,     # every 4 hours
    "crypto_day":                  1,     # every 5 min
    "crypto_lt":                   168,   # weekly
    "crypto_onchain":              8,     # every 4 hours
    "options_income":              24,    # equity income — once daily
    "options_directional":         24,    # equity directional — once daily
    "crypto_quant_aggressive":     1,     # every 5 min
    "crypto_quant_scalper":        0.5,   # every 1 min
    "crypto_quant_mean_reversion": 0.5,  # every 3 min
    "crypto_meanrev_2163":         1,     # every ~5-15 min
}

_STOCK_OPTIONS_BOTS = {
    "stock_swing", "stock_day", "stock_lt", "options_income", "options_directional"
}

_HARD_PAUSE_REASONS = {"admin_lock", "health_halt"}


def _check_bot_windows(db: Session) -> list[dict]:
    """Per-bot execution window check. Skips stock/options bots on weekends."""
    from app.db.models.bots import BotProfile, BotAllocation, BotSignal
    from sqlalchemy import func

    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() >= 5

    results: list[dict] = []
    for bot_name, max_hours in _EXPECTED_INTERVAL_HOURS.items():
        if is_weekend and bot_name in _STOCK_OPTIONS_BOTS:
            results.append({"bot": bot_name, "status": "SKIPPED", "reason": "weekend"})
            continue

        try:
            prof = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
            if not prof:
                results.append({"bot": bot_name, "status": "UNKNOWN", "reason": "no_profile"})
                continue

            alloc = db.query(BotAllocation).filter(
                BotAllocation.profile_id == prof.id,
            ).first()
            if not alloc:
                results.append({"bot": bot_name, "status": "NO_ALLOC", "reason": "no_allocation_row"})
                continue
            if not alloc.enabled:
                results.append({"bot": bot_name, "status": "DISABLED"})
                continue
            if alloc.paused_reason in _HARD_PAUSE_REASONS:
                results.append({"bot": bot_name, "status": "DISABLED", "reason": alloc.paused_reason})
                continue

            last_ts = db.query(func.max(BotSignal.ts)).filter(
                BotSignal.allocation_id == alloc.id,
            ).scalar()

            if last_ts is None:
                results.append({"bot": bot_name, "status": "NEVER_RAN", "last_signal": None})
                continue

            if last_ts.tzinfo is None:
                last_ts = last_ts.replace(tzinfo=timezone.utc)

            hours_since = (now - last_ts).total_seconds() / 3600
            threshold = max_hours * 2  # alert at 2× normal interval
            status = "OK" if hours_since <= threshold else "STALE"

            results.append({
                "bot":                    bot_name,
                "status":                 status,
                "hours_since_last":       round(hours_since, 1),
                "alert_threshold_hours":  threshold,
                "last_signal":            last_ts.isoformat(),
            })
        except Exception as exc:
            results.append({"bot": bot_name, "status": "ERROR", "reason": str(exc)[:80]})

    return results


def _check_alpaca() -> dict:
    """Ping Alpaca paper account. Returns status + equity snapshot."""
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret  = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or not secret:
        return {"status": "UNCONFIGURED", "reason": "missing credentials"}

    try:
        from alpaca.trading.client import TradingClient
        client  = TradingClient(api_key, secret, paper=True)
        account = client.get_account()

        equity        = float(account.equity or 0)
        buying_power  = float(account.buying_power or 0)
        account_status = str(account.status)

        return {
            "status":           "OK" if "ACTIVE" in account_status.upper() else "DEGRADED",
            "account_status":   account_status,
            "equity_usd":       round(equity, 2),
            "buying_power_usd": round(buying_power, 2),
        }
    except Exception as exc:
        return {"status": "ERROR", "reason": str(exc)[:120]}


def _check_signal_rate(db: Session) -> dict:
    """Compare today's signal volume against the 7-day daily average."""
    try:
        from app.db.models.bots import BotSignal
        from sqlalchemy import func

        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        week_ago    = today_start - timedelta(days=7)

        today_count = db.query(func.count(BotSignal.id)).filter(
            BotSignal.ts >= today_start,
        ).scalar() or 0

        week_count = db.query(func.count(BotSignal.id)).filter(
            BotSignal.ts >= week_ago,
            BotSignal.ts <  today_start,
        ).scalar() or 0

        daily_avg = week_count / 7 if week_count else 0

        if today_count == 0 and daily_avg > 5:
            rate_status = "SILENT"
        elif daily_avg > 0 and today_count < daily_avg * 0.25:
            rate_status = "SLOW"
        else:
            rate_status = "OK"

        return {
            "status":       rate_status,
            "today":        today_count,
            "daily_avg_7d": round(daily_avg, 1),
            "pct_of_avg":   round(today_count / daily_avg * 100, 1) if daily_avg > 0 else None,
        }
    except Exception as exc:
        return {"status": "ERROR", "reason": str(exc)[:80]}


def get_pnl_snapshot(db: Session) -> dict:
    """Today's P&L across all enabled bots — realized, unrealized, fees, winners/losers."""
    try:
        from app.db.models.bots import BotAllocation, BotDailyPnL, BotTrade, BotPosition
        from sqlalchemy import func

        today       = date.today()
        today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)

        alloc_ids = [
            a.id for a in db.query(BotAllocation).filter(BotAllocation.enabled.is_(True)).all()
        ]
        if not alloc_ids:
            return {"realized_cents": 0, "unrealized_cents": 0, "total_cents": 0,
                    "fees_cents": 0, "trade_count": 0, "open_positions": 0,
                    "top_winners": [], "top_losers": []}

        pnl_rows   = db.query(BotDailyPnL).filter(
            BotDailyPnL.allocation_id.in_(alloc_ids),
            BotDailyPnL.date == today,
        ).all()
        realized   = sum((r.realized_cents   or 0) for r in pnl_rows)
        unrealized = sum((r.unrealized_cents or 0) for r in pnl_rows)
        fees       = sum((r.fees_cents       or 0) for r in pnl_rows)

        trades = db.query(BotTrade).filter(
            BotTrade.allocation_id.in_(alloc_ids),
            BotTrade.side == "sell",
            BotTrade.created_at >= today_start,
        ).all()

        trade_pnl = sorted(
            [{"symbol": t.symbol or "?", "pnl_cents": int(t.pnl_cents or 0)} for t in trades],
            key=lambda x: -x["pnl_cents"],
        )

        open_count = db.query(func.count(BotPosition.id)).filter(
            BotPosition.allocation_id.in_(alloc_ids),
            BotPosition.closed_at.is_(None),
            BotPosition.quarantined_at.is_(None),
        ).scalar() or 0

        return {
            "realized_cents":   realized,
            "unrealized_cents": unrealized,
            "fees_cents":       fees,
            "total_cents":      realized + unrealized - fees,
            "trade_count":      len(trades),
            "top_winners":      trade_pnl[:3],
            "top_losers":       list(reversed(trade_pnl))[:3],
            "open_positions":   open_count,
        }
    except Exception as exc:
        logger.warning("[strategy_monitor] pnl_snapshot failed: %s", exc)
        return {"realized_cents": 0, "unrealized_cents": 0, "total_cents": 0,
                "fees_cents": 0, "trade_count": 0, "open_positions": 0,
                "top_winners": [], "top_losers": []}


def run_strategy_health_check(db: Session) -> dict:
    """
    Main entry point called by Queen Agent at 7 AM ET.

    Returns dict with keys: status, bots, alpaca, signal_rate, alerts, checked_at.
    Overall status: GREEN | YELLOW | RED.
    """
    bot_windows = _check_bot_windows(db)
    alpaca      = _check_alpaca()
    signal_rate = _check_signal_rate(db)

    alerts: list[str] = []

    stale_bots = [b for b in bot_windows if b.get("status") == "STALE"]
    for b in stale_bots:
        alerts.append(f"STALE: {b['bot']} silent {b.get('hours_since_last', '?')}h (threshold {b.get('alert_threshold_hours', '?')}h)")

    never_ran = [b["bot"] for b in bot_windows if b.get("status") == "NEVER_RAN"]
    if never_ran:
        alerts.append(f"NEVER RAN: {', '.join(never_ran)}")

    if alpaca.get("status") not in ("OK", "UNCONFIGURED"):
        alerts.append(f"ALPACA {alpaca.get('status')}: {alpaca.get('reason', '')}")

    sr_status = signal_rate.get("status")
    if sr_status == "SILENT":
        alerts.append(
            f"SIGNAL SILENT: 0 signals today vs {signal_rate.get('daily_avg_7d')} avg/day"
        )
    elif sr_status == "SLOW":
        alerts.append(
            f"SIGNAL SLOW: {signal_rate.get('today')} today vs avg {signal_rate.get('daily_avg_7d')}/day"
        )

    if stale_bots or alpaca.get("status") == "ERROR":
        overall = "RED"
    elif never_ran or sr_status in ("SILENT", "SLOW"):
        overall = "YELLOW"
    else:
        overall = "GREEN"

    logger.info(
        "[strategy_monitor] status=%s bots=%d stale=%d alpaca=%s signals=%s alerts=%d",
        overall, len(bot_windows), len(stale_bots),
        alpaca.get("status"), sr_status, len(alerts),
    )

    return {
        "status":      overall,
        "bots":        bot_windows,
        "alpaca":      alpaca,
        "signal_rate": signal_rate,
        "alerts":      alerts,
        "checked_at":  datetime.now(timezone.utc).isoformat(),
    }
