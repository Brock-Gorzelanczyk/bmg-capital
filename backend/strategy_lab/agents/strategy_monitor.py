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
# Derived from each bot's YAML cadence cron string.
# GREEN  : minutes_since_last ≤ 2× expected
# YELLOW : minutes_since_last ≤ 4× expected
# RED    : minutes_since_last > 4× expected, OR signals > 0 but discord_posts == 0
_EXPECTED_INTERVAL_MINUTES: dict[str, int] = {
    # Stock / equity bots (market-hours only, weekdays)
    "stock_swing":                 1440,   # "50 15 * * 1-5" — once post-close
    "stock_day":                   30,     # "*/5 4-19 * * 1-5" — 5min during hours
    "stock_lt":                    10080,  # "0 10 * * 2" — weekly
    "options_income":              60,     # "0,30 10-15 * * 1-5" — 30min during hours
    "options_directional":         60,     # "0,30 10-15 * * 1-5" — 30min during hours
    # Crypto bots (24/7)
    "crypto_swing":                480,    # "0 */4 * * *" — every 4h
    "crypto_day":                  30,     # "*/5 * * * *" — every 5min
    "crypto_lt":                   10080,  # "0 10 * * 1" — weekly
    "crypto_onchain":              480,    # "30 */4 * * *" — every 4h
    # Quant bots (24/7, high frequency)
    "crypto_quant_aggressive":     20,     # "*/5 * * * *" — every 5min
    "crypto_quant_scalper":        5,      # "*/1 * * * *" — every 1min
    "crypto_quant_mean_reversion": 10,     # "*/3 * * * *" — every 3min
    # T0 incubation / slow bots (disabled in prod)
    "crypto_meanrev_2163":         240,    # "0 */4 * * *" — every 4h (T0)
    "tsmom_multi_asset":           10080,  # "0 17 * * 5" — weekly Friday
    "quality_factor":              43200,  # quarterly rebalance (T0)
    "value_quality":               43200,  # quarterly rebalance (T0)
    "earnings_nlp":                1440,   # "0 9 * * 1-5" — daily (T0, blocked)
}

# T0 incubation bots — disabled, exempt from RED alerts
_T0_BOTS = {
    "crypto_meanrev_2163", "tsmom_multi_asset", "quality_factor",
    "value_quality", "earnings_nlp",
}

_STOCK_EQUITY_BOTS = {
    "stock_swing", "stock_day", "stock_lt", "options_income", "options_directional"
}

_HARD_PAUSE_REASONS = {"admin_lock", "health_halt"}

_BOT_SLEEVE = {
    "stock_swing": "stocks", "stock_day": "stocks", "stock_lt": "stocks",
    "options_income": "options", "options_directional": "options",
    "crypto_swing": "crypto", "crypto_day": "crypto",
    "crypto_lt": "crypto", "crypto_onchain": "crypto",
    "crypto_quant_aggressive": "quant", "crypto_quant_scalper": "quant",
    "crypto_quant_mean_reversion": "quant", "crypto_meanrev_2163": "quant",
}


def _compute_pipeline_health(
    bot_name: str,
    last_signal_ts,
    signals_24h: int,
    discord_posts_24h: int,
    expected_interval_min: int,
    is_enabled: bool,
    paused_reason: Optional[str],
    is_weekend: bool,
    now: datetime,
) -> str:
    """Return GREEN / YELLOW / RED / DISABLED based on cadence-aware thresholds."""
    if not is_enabled or paused_reason in _HARD_PAUSE_REASONS or bot_name in _T0_BOTS:
        return "DISABLED"

    # Posting gap: signals fired but Discord didn't post at least one
    has_posting_gap = signals_24h > 0 and discord_posts_24h < signals_24h

    if last_signal_ts is None:
        # Weekly / slow bots never ran yet — YELLOW; faster bots — RED
        return "YELLOW" if expected_interval_min >= 10080 else "RED"

    if last_signal_ts.tzinfo is None:
        last_signal_ts = last_signal_ts.replace(tzinfo=timezone.utc)
    minutes_since = (now - last_signal_ts).total_seconds() / 60

    # Equity bots are expected silent on weekends
    if is_weekend and bot_name in _STOCK_EQUITY_BOTS:
        return "YELLOW" if has_posting_gap else "GREEN"

    if signals_24h > 0 and discord_posts_24h == 0:
        return "RED"

    if minutes_since <= expected_interval_min * 2:
        return "YELLOW" if has_posting_gap else "GREEN"
    if minutes_since <= expected_interval_min * 4:
        return "YELLOW"
    return "RED"


def _check_bot_windows(db: Session) -> list[dict]:
    """Per-bot execution health. Returns pipeline_health GREEN/YELLOW/RED per bot."""
    from app.db.models.bots import BotProfile, BotAllocation, BotSignal, BotTrade, BotPosition
    from sqlalchemy import func, and_

    now = datetime.now(timezone.utc)
    is_weekend = now.weekday() >= 5
    cutoff_24h = (now - timedelta(hours=24)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")

    results: list[dict] = []
    for bot_name, interval_min in _EXPECTED_INTERVAL_MINUTES.items():
        try:
            prof = db.query(BotProfile).filter(BotProfile.name == bot_name).first()
            if not prof:
                results.append({"bot": bot_name, "pipeline_health": "RED",
                                 "status": "UNKNOWN", "reason": "no_profile"})
                continue

            # Get ALL allocations for this profile (any user) so signal + trade
            # counts are accurate even when activity spans multiple allocations.
            alloc_rows = db.query(BotAllocation).filter(
                BotAllocation.profile_id == prof.id,
            ).all()
            if not alloc_rows:
                results.append({"bot": bot_name, "pipeline_health": "RED",
                                 "status": "NO_ALLOC", "reason": "no_allocation_row"})
                continue
            alloc = alloc_rows[0]
            alloc_ids = [a.id for a in alloc_rows]

            # Signal stats — aggregated across all allocations for this profile
            last_ts = db.query(func.max(BotSignal.ts)).filter(
                BotSignal.allocation_id.in_(alloc_ids),
                BotSignal.is_test.is_(None) | (BotSignal.is_test == False),  # noqa: E712
            ).scalar()

            signals_24h = db.query(func.count(BotSignal.id)).filter(
                BotSignal.allocation_id.in_(alloc_ids),
                BotSignal.ts >= cutoff_24h,
                BotSignal.is_test.is_(None) | (BotSignal.is_test == False),  # noqa: E712
            ).scalar() or 0

            discord_posts_24h = db.query(func.count(BotSignal.id)).filter(
                BotSignal.allocation_id.in_(alloc_ids),
                BotSignal.ts >= cutoff_24h,
                BotSignal.discord_posted_at.isnot(None),
                BotSignal.is_test.is_(None) | (BotSignal.is_test == False),  # noqa: E712
            ).scalar() or 0

            trades_24h = db.query(func.count(BotTrade.id)).filter(
                BotTrade.allocation_id.in_(alloc_ids),
                BotTrade.ts >= cutoff_24h,
                BotTrade.quarantined_at.is_(None),
            ).scalar() or 0

            open_positions = db.query(func.count(BotPosition.id)).filter(
                BotPosition.allocation_id.in_(alloc_ids),
                BotPosition.closed_at.is_(None),
                BotPosition.quarantined_at.is_(None),
            ).scalar() or 0

            health = _compute_pipeline_health(
                bot_name=bot_name,
                last_signal_ts=last_ts,
                signals_24h=signals_24h,
                discord_posts_24h=discord_posts_24h,
                expected_interval_min=interval_min,
                is_enabled=bool(alloc.enabled),
                paused_reason=alloc.paused_reason,
                is_weekend=is_weekend,
                now=now,
            )

            minutes_since = None
            if last_ts is not None:
                lts = last_ts if last_ts.tzinfo else last_ts.replace(tzinfo=timezone.utc)
                minutes_since = round((now - lts).total_seconds() / 60, 1)

            # A14: categorize why a bot is DISABLED for dashboard display
            disable_category: str | None = None
            if health == "DISABLED":
                if bot_name in _T0_BOTS:
                    disable_category = "T0_INCUBATION"
                elif alloc.paused_reason == "admin_lock":
                    disable_category = "ADMIN_LOCK"
                elif alloc.paused_reason == "health_halt":
                    disable_category = "HEALTH_HALT"
                else:
                    disable_category = "NOT_ENABLED"

            results.append({
                "bot":                    bot_name,
                "pipeline_health":        health,
                "status":                 "DISABLED" if health == "DISABLED" else ("STALE" if health == "RED" else "OK"),
                "enabled":                bool(alloc.enabled),
                "paused_reason":          alloc.paused_reason,
                "disable_category":       disable_category,
                "last_signal_at":         last_ts.isoformat() if last_ts else None,
                "minutes_since_last":     minutes_since,
                "signals_24h":            signals_24h,
                "discord_posts_24h":      discord_posts_24h,
                "trades_24h":             trades_24h,
                "open_positions":         open_positions,
                "expected_interval_min":  interval_min,
                "alert_threshold_min":    interval_min * 4,
            })
        except Exception as exc:
            results.append({
                "bot":             bot_name,
                "pipeline_health": "RED",
                "status":          "ERROR",
                "reason":          str(exc)[:120],
            })

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
    """
    Portfolio P&L from BotTrade + BotPosition — same source as the canonical endpoint.
    BotDailyPnL is intentionally NOT used (it is an audit log, not the live source of truth).
    Returns all-time realized + current unrealized, plus today's realized for the sub-line.
    """
    try:
        from app.db.models.bots import BotAllocation, BotTrade, BotPosition
        from sqlalchemy import func

        today       = date.today()
        today_start = datetime.combine(today, datetime.min.time()).replace(tzinfo=timezone.utc)

        # All allocations — no enabled filter (matches canonical endpoint)
        alloc_ids = [a.id for a in db.query(BotAllocation).all()]
        if not alloc_ids:
            return {"realized_cents": 0, "unrealized_cents": 0, "total_cents": 0,
                    "fees_cents": 0, "today_cents": 0, "trade_count": 0,
                    "open_positions": 0, "top_winners": [], "top_losers": []}

        # Avg-cost lookup from all positions
        all_positions = db.query(BotPosition).filter(
            BotPosition.allocation_id.in_(alloc_ids),
        ).all()
        pos_cost_map: dict[int, float] = {p.id: p.avg_cost_cents for p in all_positions}

        # All trades (buy side provides fallback avg_cost by allocation+symbol)
        all_trades = db.query(BotTrade).filter(
            BotTrade.allocation_id.in_(alloc_ids),
            BotTrade.quarantined_at.is_(None),
        ).order_by(BotTrade.ts).all()

        buy_price: dict[tuple, float] = {}
        for t in all_trades:
            if t.side.lower() in ("buy", "open", "short"):
                buy_price[(t.allocation_id, t.symbol)] = t.fill_price_cents

        realized_cents = 0
        today_realized = 0
        trade_pnl: list[dict] = []

        for t in all_trades:
            side = t.side.lower()
            if side not in ("sell", "close", "cover"):
                continue
            avg_cost = pos_cost_map.get(t.position_id) if t.position_id else None
            if avg_cost is None:
                avg_cost = buy_price.get((t.allocation_id, t.symbol), t.fill_price_cents)
            if side == "cover":
                pnl = int((avg_cost - t.fill_price_cents) * t.qty) - int(t.fees_cents or 0)
            else:
                pnl = int((t.fill_price_cents - avg_cost) * t.qty) - int(t.fees_cents or 0)
            realized_cents += pnl
            trade_date = t.ts.date() if hasattr(t.ts, "date") else t.ts
            if trade_date == today:
                today_realized += pnl
            trade_pnl.append({"symbol": t.symbol or "?", "pnl_cents": pnl})

        # Open positions for count and unrealized P&L
        open_pos = [p for p in all_positions if p.closed_at is None and not p.quarantined_at]
        open_count = len(open_pos)

        unrealized_cents = 0
        try:
            from app.core.canonical import _cached_live_prices
            syms = list({p.symbol for p in open_pos})
            prices = _cached_live_prices(syms)
            for p in open_pos:
                price = prices.get(p.symbol)
                if price and p.avg_cost_cents and p.qty:
                    unrealized_cents += int((price * 100 - p.avg_cost_cents) * p.qty)
        except Exception:
            pass

        trade_pnl.sort(key=lambda x: -x["pnl_cents"])
        today_trade_count = sum(
            1 for t in all_trades
            if t.side.lower() in ("sell", "close")
            and (t.ts.date() if hasattr(t.ts, "date") else t.ts) == today
        )

        return {
            "realized_cents":   realized_cents,
            "unrealized_cents": unrealized_cents,
            "fees_cents":       0,
            "total_cents":      realized_cents + unrealized_cents,
            "today_cents":      today_realized,
            "trade_count":      today_trade_count,
            "top_winners":      trade_pnl[:3],
            "top_losers":       list(reversed(trade_pnl))[:3],
            "open_positions":   open_count,
        }
    except Exception as exc:
        logger.warning("[strategy_monitor] pnl_snapshot failed: %s", exc)
        return {"realized_cents": 0, "unrealized_cents": 0, "total_cents": 0,
                "fees_cents": 0, "today_cents": 0, "trade_count": 0,
                "open_positions": 0, "top_winners": [], "top_losers": []}


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

    # Use pipeline_health GREEN/YELLOW/RED — RED bots trigger alerts
    red_bots = [b for b in bot_windows if b.get("pipeline_health") == "RED"]
    yellow_bots = [b for b in bot_windows if b.get("pipeline_health") == "YELLOW"]
    for b in red_bots:
        alerts.append(
            f"RED: {b['bot']} silent {b.get('minutes_since_last') or '∞'}m "
            f"(threshold {b.get('alert_threshold_min','?')}m, signals_24h={b.get('signals_24h',0)})"
        )
    for b in yellow_bots:
        alerts.append(
            f"YELLOW: {b['bot']} slow — {b.get('signals_24h',0)} signals in 24h, "
            f"{b.get('discord_posts_24h',0)} posted to Discord"
        )

    # Legacy compat: still populate stale_bots for callers that check it
    stale_bots = red_bots + yellow_bots

    never_ran = [b["bot"] for b in bot_windows if b.get("last_signal_at") is None
                 and b.get("pipeline_health") not in ("DISABLED",)]
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

    # A15: fire Discord alerts on RED transitions (non-fatal)
    try:
        n_posted = post_health_transition_alerts(db, bot_windows)
        if n_posted:
            logger.warning("[strategy_monitor] %d RED-transition alert(s) posted to Discord", n_posted)
    except Exception as _exc:
        logger.debug("[strategy_monitor] health transition alerts failed: %s", _exc)

    return {
        "status":      overall,
        "bots":        bot_windows,
        "alpaca":      alpaca,
        "signal_rate": signal_rate,
        "alerts":      alerts,
        "checked_at":  datetime.now(timezone.utc).isoformat(),
    }


# ── A15: health transition alerts to Discord ──────────────────────────────────

def _ensure_bot_health_state_table(db: Session) -> None:
    try:
        from sqlalchemy import text as sql_text
        db.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS bot_health_state (
                bot_name      TEXT PRIMARY KEY,
                last_health   TEXT NOT NULL,
                alerted_at    TEXT,
                updated_at    TEXT NOT NULL
            )
        """))
        db.commit()
    except Exception as exc:
        logger.debug("[strategy_monitor] bot_health_state table ensure failed: %s", exc)


def _read_health_state(db: Session) -> dict[str, dict]:
    """Return {bot_name: {last_health, alerted_at}} from bot_health_state table."""
    try:
        from sqlalchemy import text as sql_text
        rows = db.execute(sql_text(
            "SELECT bot_name, last_health, alerted_at FROM bot_health_state"
        )).fetchall()
        return {r[0]: {"last_health": r[1], "alerted_at": r[2]} for r in rows}
    except Exception:
        return {}


def _write_health_state(db: Session, bot_name: str, health: str, alerted_at: str | None = None) -> None:
    try:
        from sqlalchemy import text as sql_text
        db.execute(sql_text("""
            INSERT INTO bot_health_state (bot_name, last_health, alerted_at, updated_at)
            VALUES (:bot, :health, :alerted, :now)
            ON CONFLICT(bot_name) DO UPDATE SET
                last_health = excluded.last_health,
                alerted_at  = COALESCE(excluded.alerted_at, bot_health_state.alerted_at),
                updated_at  = excluded.updated_at
        """), {
            "bot":     bot_name,
            "health":  health,
            "alerted": alerted_at,
            "now":     datetime.now(timezone.utc).isoformat(),
        })
        db.commit()
    except Exception as exc:
        logger.debug("[strategy_monitor] _write_health_state failed for %s: %s", bot_name, exc)


def _post_risk_alert(bot_row: dict, now: datetime) -> bool:
    """Post a RED transition alert to #risk-alerts Discord channel."""
    import os
    import httpx

    token      = os.getenv("DISCORD_BOT_TOKEN", "")
    channel_id = os.getenv("DISCORD_CH_RISK_ALERTS", "") or os.getenv("DISCORD_CH_DEV_LOG", "")
    if not token or not channel_id:
        logger.debug("[strategy_monitor] risk-alert skipped — no Discord config")
        return False

    bot_name       = bot_row.get("bot", "unknown")
    minutes_stale  = bot_row.get("minutes_since_last")
    signals_24h    = bot_row.get("signals_24h", 0)
    trades_24h     = bot_row.get("trades_24h", 0)
    open_positions = bot_row.get("open_positions", 0)
    expected_min   = bot_row.get("expected_interval_min", "?")
    detail_url     = f"/admin/bot-health/{bot_name}"

    if minutes_stale:
        last_signal_str = f"{minutes_stale:.0f} minutes ago"
        expected_str    = f"every {expected_min} min"
    else:
        last_signal_str = "never"
        expected_str    = f"every {expected_min} min"

    description = (
        f"🔴 **{bot_name}** flipped to RED at {now.strftime('%I:%M %p ET')}.\n\n"
        f"Last signal: {last_signal_str} (expected: {expected_str}).\n"
        f"Open positions: **{open_positions}**. Trades 24h: **{trades_24h}**.\n\n"
        f"Drill-down: `{detail_url}`"
    )

    embed = {
        "title":       f"🔴 Bot Health Alert — {bot_name}",
        "description": description,
        "color":       0xDC2626,
        "fields": [
            {"name": "Signals 24h",    "value": str(signals_24h),    "inline": True},
            {"name": "Trades 24h",     "value": str(trades_24h),     "inline": True},
            {"name": "Open Positions", "value": str(open_positions),  "inline": True},
        ],
        "footer":    {"text": f"strategy_monitor · {now.strftime('%Y-%m-%d %H:%M UTC')}"},
        "timestamp": now.isoformat(),
    }

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    try:
        with httpx.Client(timeout=10) as client:
            resp = client.post(
                url,
                headers={
                    "Authorization": f"Bot {token}",
                    "Content-Type":  "application/json",
                    "User-Agent":    "DiscordBot (https://github.com/BMG-Capital/bmg-capital, 1.0.0)",
                },
                json={"embeds": [embed]},
            )
        return resp.is_success
    except Exception as exc:
        logger.error("[strategy_monitor] risk-alert Discord post failed: %s", exc)
        return False


def post_health_transition_alerts(db: Session, bot_windows: list[dict]) -> int:
    """
    Called from run_strategy_health_check. Compares current health against stored
    state. Posts to #risk-alerts when a bot transitions to RED, with 6h dedup per bot.
    Returns number of alerts posted.
    """
    _ensure_bot_health_state_table(db)
    previous = _read_health_state(db)
    now      = datetime.now(timezone.utc)
    posted   = 0

    for bot_row in bot_windows:
        bot_name   = bot_row.get("bot", "")
        cur_health = bot_row.get("pipeline_health", "")

        prev_entry = previous.get(bot_name, {})
        prev_health = prev_entry.get("last_health", "UNKNOWN")
        alerted_at  = prev_entry.get("alerted_at")

        # Only alert on transition TO RED (not staying RED)
        if cur_health == "RED" and prev_health != "RED":
            # 6h dedup — skip if we already alerted for this bot in the last 6h
            within_cooldown = False
            if alerted_at:
                try:
                    alerted_dt = datetime.fromisoformat(alerted_at)
                    if alerted_dt.tzinfo is None:
                        alerted_dt = alerted_dt.replace(tzinfo=timezone.utc)
                    within_cooldown = (now - alerted_dt).total_seconds() < 6 * 3600
                except Exception:
                    pass

            if not within_cooldown:
                success = _post_risk_alert(bot_row, now)
                alerted_iso = now.isoformat() if success else None
                _write_health_state(db, bot_name, cur_health, alerted_at=alerted_iso)
                if success:
                    posted += 1
                    logger.warning("[strategy_monitor] risk-alert posted: %s GREEN/YELLOW→RED", bot_name)
                else:
                    _write_health_state(db, bot_name, cur_health)
            else:
                _write_health_state(db, bot_name, cur_health)
        else:
            _write_health_state(db, bot_name, cur_health)

    return posted
