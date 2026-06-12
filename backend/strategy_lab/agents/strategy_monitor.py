"""
Strategy Monitor Agent — system and bot execution health.

Called by Queen Agent for all 4 daily sessions plus regime alert checks.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone, timedelta, date
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Per-bot expected signal interval in MINUTES.
# STALE threshold fires at 3× this value — slow bots never false-alarm.
_EXPECTED_INTERVAL_MINUTES: dict[str, int] = {
    "stock_swing":                 1440,   # once post-close (24h)
    "stock_day":                   30,     # every 5 min during hours
    "stock_lt":                    10080,  # weekly
    "crypto_swing":                480,    # every 4h
    "crypto_day":                  30,     # every 5 min, 24/7
    "crypto_lt":                   10080,  # weekly
    "crypto_onchain":              480,    # every 4h
    "options_income":              1440,   # equity income — once daily
    "options_directional":         1440,   # equity directional — once daily
    "crypto_quant_aggressive":     20,     # every 5 min
    "crypto_quant_scalper":        10,     # every 1 min
    "crypto_quant_mean_reversion": 15,     # every 3 min
    "crypto_meanrev_2163":         240,    # every 4h
}

_STOCK_EQUITY_BOTS = {
    "stock_swing", "stock_day", "stock_lt", "options_income", "options_directional"
}

_HARD_PAUSE_REASONS = {"admin_lock", "health_halt"}

_BOT_SLEEVE = {
    "stock_swing": "stocks", "stock_day": "stocks", "stock_lt": "stocks",
    "options_income": "stocks", "options_directional": "stocks",
    "crypto_swing": "crypto", "crypto_day": "crypto",
    "crypto_lt": "crypto", "crypto_onchain": "crypto",
    "crypto_quant_aggressive": "quant", "crypto_quant_scalper": "quant",
    "crypto_quant_mean_reversion": "quant", "crypto_meanrev_2163": "quant",
}


def _check_bot_windows(db: Session) -> list[dict]:
    """Per-bot execution window check. Skips stock/equity bots on weekends."""
    from app.db.models.bots import BotProfile, BotAllocation, BotSignal
    from sqlalchemy import func

    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() >= 5

    results: list[dict] = []
    for bot_name, interval_min in _EXPECTED_INTERVAL_MINUTES.items():
        if is_weekend and bot_name in _STOCK_EQUITY_BOTS:
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

            minutes_since = (now - last_ts).total_seconds() / 60
            threshold_min = interval_min * 3  # STALE at 3× expected interval
            status = "OK" if minutes_since <= threshold_min else "STALE"

            results.append({
                "bot":                    bot_name,
                "status":                 status,
                "minutes_since_last":     round(minutes_since, 1),
                "alert_threshold_min":    threshold_min,
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

        equity       = float(account.equity or 0)
        buying_power = float(account.buying_power or 0)

        return {
            "status":           "OK" if "ACTIVE" in str(account.status).upper() else "DEGRADED",
            "account_status":   str(account.status),
            "equity_usd":       round(equity, 2),
            "buying_power_usd": round(buying_power, 2),
        }
    except Exception as exc:
        return {"status": "ERROR", "reason": str(exc)[:120]}


def _check_signal_rate(db: Session) -> dict:
    """Compare today's signal volume against 7-day daily average."""
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


def get_weekend_pnl(db: Session) -> dict:
    """Sat+Sun P&L broken down by sleeve — used in Monday 6am crypto recap."""
    try:
        from app.db.models.bots import BotAllocation, BotDailyPnL, BotProfile
        from sqlalchemy import func

        today    = date.today()
        weekday  = today.weekday()
        # Compute the most recent Saturday
        days_since_sat = (weekday - 5) % 7
        saturday = today - timedelta(days=days_since_sat)
        sunday   = saturday + timedelta(days=1)

        allocs = db.query(BotAllocation, BotProfile).join(
            BotProfile, BotProfile.id == BotAllocation.profile_id
        ).all()

        sleeve_totals: dict[str, int] = {"stocks": 0, "crypto": 0, "quant": 0}
        total = 0

        for alloc, profile in allocs:
            sleeve = _BOT_SLEEVE.get(profile.name, "other")
            if sleeve not in sleeve_totals:
                continue
            rows = db.query(BotDailyPnL).filter(
                BotDailyPnL.allocation_id == alloc.id,
                BotDailyPnL.date.in_([saturday, sunday]),
            ).all()
            cents = sum((r.realized_cents or 0) + (r.unrealized_cents or 0) for r in rows)
            sleeve_totals[sleeve] = sleeve_totals.get(sleeve, 0) + cents
            total += cents

        return {
            "total_cents":   total,
            "by_sleeve":     sleeve_totals,
            "saturday":      saturday.isoformat(),
            "sunday":        sunday.isoformat(),
        }
    except Exception as exc:
        logger.warning("[strategy_monitor] weekend_pnl failed: %s", exc)
        return {"total_cents": 0, "by_sleeve": {}, "saturday": "", "sunday": ""}


def get_weekly_pnl(db: Session) -> dict:
    """7-day P&L by sleeve and top/bottom bots — used in Sunday weekly digest."""
    try:
        from app.db.models.bots import BotAllocation, BotDailyPnL, BotProfile
        from app.db.models.allocation import BotPerformanceStats

        week_ago = date.today() - timedelta(days=7)

        allocs = db.query(BotAllocation, BotProfile).join(
            BotProfile, BotProfile.id == BotAllocation.profile_id
        ).all()

        sleeve_totals: dict[str, int] = {"stocks": 0, "crypto": 0, "quant": 0}
        bot_pnls: list[dict] = []

        for alloc, profile in allocs:
            sleeve = _BOT_SLEEVE.get(profile.name, "other")
            rows = db.query(BotDailyPnL).filter(
                BotDailyPnL.allocation_id == alloc.id,
                BotDailyPnL.date >= week_ago,
            ).all()
            cents = sum((r.realized_cents or 0) + (r.unrealized_cents or 0) for r in rows)
            if sleeve in sleeve_totals:
                sleeve_totals[sleeve] += cents
            bot_pnls.append({"bot": profile.name, "pnl_cents": cents})

        bot_pnls.sort(key=lambda x: -x["pnl_cents"])
        total = sum(sleeve_totals.values())

        return {
            "total_cents":   total,
            "by_sleeve":     sleeve_totals,
            "top_bots":      bot_pnls[:3],
            "bottom_bots":   list(reversed(bot_pnls))[:3],
        }
    except Exception as exc:
        logger.warning("[strategy_monitor] weekly_pnl failed: %s", exc)
        return {"total_cents": 0, "by_sleeve": {}, "top_bots": [], "bottom_bots": []}


def check_regime_alert_signals(db: Session) -> list[dict]:
    """
    Poll for regime-change alert conditions. Returns list of triggered alerts.
    Each alert: {"signal": str, "description": str, "severity": "HIGH"|"MEDIUM"}.
    """
    alerts: list[dict] = []
    try:
        from sqlalchemy import text

        # ── Try new regime_snapshots table first (from Playbook Phase 2) ──────
        rows = db.execute(text("""
            SELECT snapshot_date, vix_level, spx_vs_200ma, hy_spread_proxy, vix_ts_slope,
                   regime, confidence
            FROM regime_snapshots
            ORDER BY snapshot_date DESC
            LIMIT 15
        """)).fetchall()

        if rows and len(rows) >= 2:
            latest = rows[0]
            vix_now = latest[1]

            # VIX +50% in 5 days
            if vix_now and len(rows) >= 5:
                vix_5d = rows[4][1]
                if vix_5d and vix_5d > 0 and (vix_now / vix_5d - 1) >= 0.50:
                    alerts.append({
                        "signal": "vix_spike_5d",
                        "description": f"VIX +{(vix_now/vix_5d-1)*100:.0f}% in 5 days ({vix_5d:.1f}→{vix_now:.1f})",
                        "severity": "HIGH",
                    })

            # VIX term structure inverted (backwardation)
            vix_ts = latest[4]
            if vix_ts is not None and vix_ts < 0:
                alerts.append({
                    "signal": "vix_backwardation",
                    "description": f"VIX term structure inverted (slope={vix_ts:.3f}) — stress signal",
                    "severity": "HIGH",
                })

            # SPX below 200 MA
            spx_vs_200 = latest[2]
            if spx_vs_200 is not None and spx_vs_200 < 0:
                # Only alert if it recently crossed below (was above 5 days ago)
                if len(rows) >= 5 and rows[4][2] is not None and rows[4][2] >= 0:
                    alerts.append({
                        "signal": "spx_below_200ma",
                        "description": "SPX crossed below 200 MA after extended period above",
                        "severity": "HIGH",
                    })

            # HY spread proxy widening
            hy_now = latest[3]
            if hy_now and len(rows) >= 10:
                hy_10d = rows[9][3]
                if hy_10d and (hy_now - hy_10d) >= 0.05:  # proxy unit threshold
                    alerts.append({
                        "signal": "hy_spread_widening",
                        "description": f"HY spread proxy widened {hy_now - hy_10d:.3f} in 10 days",
                        "severity": "MEDIUM",
                    })

    except Exception:
        pass  # Table may not exist yet — fall back to old table

    try:
        # ── Fall back to original regime_snapshot table ───────────────────────
        from app.db.models.bots import RegimeSnapshot
        snaps = db.query(RegimeSnapshot).order_by(RegimeSnapshot.ts.desc()).limit(15).all()

        if snaps and len(snaps) >= 2:
            vix_now = snaps[0].vix_value

            # VIX +50% in 5 days
            if vix_now and len(snaps) >= 5:
                vix_5d = snaps[4].vix_value
                if vix_5d and vix_5d > 0 and (vix_now / vix_5d - 1) >= 0.50:
                    if not any(a["signal"] == "vix_spike_5d" for a in alerts):
                        alerts.append({
                            "signal": "vix_spike_5d",
                            "description": f"VIX +{(vix_now/vix_5d-1)*100:.0f}% in 5 days ({vix_5d:.1f}→{vix_now:.1f})",
                            "severity": "HIGH",
                        })

            # BTC dominance ±3pts in 7 days
            btc_now = snaps[0].btc_dominance
            if btc_now and len(snaps) >= 7:
                btc_7d = snaps[6].btc_dominance
                if btc_7d and abs(btc_now - btc_7d) >= 3.0:
                    direction = "▲" if btc_now > btc_7d else "▼"
                    alerts.append({
                        "signal": "btc_dom_shift",
                        "description": f"BTC dominance {direction}{abs(btc_now-btc_7d):.1f}pts in 7d ({btc_7d:.1f}%→{btc_now:.1f}%)",
                        "severity": "MEDIUM",
                    })

            # Regime transition into crisis
            current_regime = (snaps[0].trend_regime or "").lower()
            prev_regime    = (snaps[1].trend_regime or "").lower() if len(snaps) > 1 else ""
            if "crisis" in current_regime and "crisis" not in prev_regime:
                if not any(a["signal"] == "regime_crisis" for a in alerts):
                    alerts.append({
                        "signal": "regime_crisis",
                        "description": "Regime transitioned into CRISIS — review all positions",
                        "severity": "HIGH",
                    })

    except Exception:
        pass

    return alerts


def run_strategy_health_check(db: Session) -> dict:
    """
    Main entry point called by Queen Agent for all 4 daily sessions.

    Returns dict with keys: status, bots, alpaca, signal_rate, alerts, checked_at.
    """
    bot_windows = _check_bot_windows(db)
    alpaca      = _check_alpaca()
    signal_rate = _check_signal_rate(db)

    alerts: list[str] = []

    stale_bots = [b for b in bot_windows if b.get("status") == "STALE"]
    for b in stale_bots:
        alerts.append(
            f"STALE: {b['bot']} silent {b.get('minutes_since_last','?'):.0f}m "
            f"(threshold {b.get('alert_threshold_min','?'):.0f}m)"
        )

    never_ran = [b["bot"] for b in bot_windows if b.get("status") == "NEVER_RAN"]
    if never_ran:
        alerts.append(f"NEVER RAN: {', '.join(never_ran)}")

    if alpaca.get("status") not in ("OK", "UNCONFIGURED"):
        alerts.append(f"ALPACA {alpaca.get('status')}: {alpaca.get('reason', '')}")

    sr_status = signal_rate.get("status")
    if sr_status == "SILENT":
        alerts.append(f"SIGNAL SILENT: 0 signals today vs {signal_rate.get('daily_avg_7d')} avg/day")
    elif sr_status == "SLOW":
        alerts.append(f"SIGNAL SLOW: {signal_rate.get('today')} today vs avg {signal_rate.get('daily_avg_7d')}/day")

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
