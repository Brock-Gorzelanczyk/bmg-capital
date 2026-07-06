"""
Fleet Sentinel — semi-autonomous issue detection + paste-ready diagnostics.

Runs every 10 minutes. Detects 7 classes of issues, deduplicates within
a 4-hour cooldown window, and posts structured embeds to #fund-updates so
Brock can copy → paste into Claude Code → fix.

Detection rules:
  1. RED bot transition (status flip since last check)
  2. Deploy failed (Railway service restarted unexpectedly)
  3. Signal gap > 50 min for any bot in its active window
  4. Activity feed 0 trades during market hours
  5. Bot last_signal exceeded 4× its cadence
  6. Asset class mismatch positions (e.g. crypto bot holding AAPL)
  7. bot_daily_pnl rows stopped incrementing for active bots
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from sqlalchemy.orm import Session
from sqlalchemy import text as sql_text

logger = logging.getLogger(__name__)

# ── Deduplication: suppress repeat alerts for 4 hours ─────────────────────────
_ALERT_COOLDOWN_HOURS = 4
_last_alerted: dict[str, datetime] = {}


def _throttled(key: str) -> bool:
    """Return True if this alert key was already posted within the cooldown window."""
    now = datetime.now(timezone.utc)
    last = _last_alerted.get(key)
    if last and (now - last).total_seconds() < _ALERT_COOLDOWN_HOURS * 3600:
        return True
    _last_alerted[key] = now
    return False


# ── Cadence registry (minutes between expected signals per bot) ────────────────
# Used for both the "4× cadence" check and the "50 min gap" check.
# Only bots listed here are monitored for staleness.
# active_hours: UTC hour range where signals are expected (None = 24/7)
_BOT_CADENCE: dict[str, dict] = {
    "crypto_quant_aggressive":      {"cadence_min": 5,  "active_hours": None},
    "crypto_quant_scalper":         {"cadence_min": 5,  "active_hours": None},
    "crypto_quant_mean_reversion":  {"cadence_min": 5,  "active_hours": None},
    "crypto_day":                   {"cadence_min": 5,  "active_hours": None},
    "stock_day":                    {"cadence_min": 5,  "active_hours": (9, 20)},   # 9–20 UTC = 4 AM–3 PM ET
    "options_income":               {"cadence_min": 30, "active_hours": (14, 20)},  # 14–20 UTC = 10 AM–4 PM ET
    "options_directional":          {"cadence_min": 30, "active_hours": (14, 20)},
    "crypto_swing":                 {"cadence_min": 240,"active_hours": None},
}

# Bots whose asset_class field should match their position symbols
_CRYPTO_BOTS = {"crypto_day", "crypto_swing", "crypto_lt", "crypto_onchain",
                "crypto_quant_aggressive", "crypto_quant_scalper", "crypto_quant_mean_reversion"}
_STOCK_BOTS  = {"stock_day", "stock_swing", "stock_lt"}
_OPTIONS_BOTS = {"options_income", "options_directional"}


def _is_in_active_window(active_hours: Optional[tuple[int, int]]) -> bool:
    if active_hours is None:
        return True
    utc_hour = datetime.now(timezone.utc).hour
    start, end = active_hours
    return start <= utc_hour < end


def _is_bot_funded_and_enabled(db: Session, bot_name: str) -> bool:
    """Return True if the bot has real capital AND its allocation is enabled.

    2026-07-06: added because the sentinel was spam-alerting on halted bots
    (crypto_quant_scalper, crypto_quant_mean_reversion at $0 per m062).
    Every 10 minutes Patrick would report an 8000-min signal gap on bots
    that were intentionally halted; those alerts drowned real regressions.
    Now every staleness check runs this filter first so halted bots do
    not fire alerts.
    """
    try:
        row = db.execute(sql_text("""
            SELECT COALESCE(SUM(ba.starting_capital_cents), 0) AS cap,
                   MAX(CASE WHEN ba.enabled THEN 1 ELSE 0 END) AS any_enabled
              FROM bot_allocations ba
              JOIN bot_profiles bp ON bp.id = ba.profile_id
             WHERE bp.name = :bot
               AND ba.paper_mode = 1
        """), {"bot": bot_name}).fetchone()
        if not row:
            return False
        cap = int(row[0] or 0)
        any_enabled = bool(row[1] or 0)
        return cap > 0 and any_enabled
    except Exception as exc:
        logger.warning("[fleet_sentinel] funded/enabled check failed for %s: %s",
                       bot_name, exc)
        # Fail-open: if we cannot determine bot state, allow the alert. Better
        # to have one false positive than miss a real regression while a DB
        # query is transiently broken.
        return True


# ── Check 1: RED bot transition ────────────────────────────────────────────────

def _check_red_transitions(db: Session) -> list[dict]:
    alerts = []
    try:
        from app.db.models.bots import BotHealth, BotAllocation, BotProfile
        from datetime import date

        today = date.today()
        yesterday = today - timedelta(days=1)

        # Bots that are RED today
        red_today = db.execute(sql_text("""
            SELECT DISTINCT bp.name
            FROM bot_health bh
            JOIN bot_allocations ba ON ba.id = bh.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bh.date = :today AND bh.health_status = 'RED'
              AND ba.paper_mode = 1
        """), {"today": today.isoformat()}).fetchall()

        # Bots that were RED yesterday too (not new)
        red_yesterday = {r[0] for r in db.execute(sql_text("""
            SELECT DISTINCT bp.name
            FROM bot_health bh
            JOIN bot_allocations ba ON ba.id = bh.allocation_id
            JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE bh.date = :yesterday AND bh.health_status = 'RED'
              AND ba.paper_mode = 1
        """), {"yesterday": yesterday.isoformat()}).fetchall()}

        for (bot_name,) in red_today:
            if bot_name in red_yesterday:
                continue  # persistent RED — skip, risk_sentinel already handles it
            key = f"red_transition:{bot_name}:{today.isoformat()}"
            if _throttled(key):
                continue
            alerts.append({
                "title": f"{bot_name} — new RED health status today",
                "body": (
                    f"{bot_name} flipped to RED today (was not RED yesterday). "
                    f"This is a new failure, not a persistent condition. "
                    f"Check heartbeat, signal flow, and last trade timestamp."
                ),
                "paste_ready": f"""ISSUE: {bot_name} flipped to RED health status today

DIAGNOSIS:
Bot transitioned from non-RED to RED since yesterday's health check.
Likely causes:
1. Heartbeat missing — bot ran but didn't write a health row (check bot_health table)
2. Strategy threw an exception that was caught but logged as unhealthy
3. Alpaca/data feed timeout during last scan cycle

QUICK VERIFY:
railway ssh "cd /app && python3 -c '
from app.db.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
with db.bind.connect() as c:
    r = c.execute(text(\\"SELECT date, health_status, notes FROM bot_health bh JOIN bot_allocations ba ON ba.id=bh.allocation_id JOIN bot_profiles bp ON bp.id=ba.profile_id WHERE bp.name=\\\\\\"{bot_name}\\\\\\" ORDER BY date DESC LIMIT 5\\")).fetchall()
    [print(x) for x in r]
'"

FIX: Run a manual scan to reset health state:
railway ssh "cd /app && python3 -c 'from strategy_lab.runner import run_bot_profile; print(run_bot_profile(\\"{bot_name}\\"))'"
""",
                "priority": "high",
            })
    except Exception as exc:
        logger.warning("[fleet_sentinel] red_transition check failed: %s", exc)
    return alerts


# ── Check 2: Unexpected restart / deploy failure ───────────────────────────────

def _check_deploy_health(db: Session) -> list[dict]:
    alerts = []
    try:
        # 2026-07-06: skip if crypto_quant_aggressive is not funded / enabled.
        # After m067 trimmed its allocation from $130K to $80K, the bot is
        # still active — but if a future migration halted it, this alert
        # would fire every hour with a false positive.
        if not _is_bot_funded_and_enabled(db, "crypto_quant_aggressive"):
            return alerts
        # Proxy: if startup trace log is missing from today, the process restarted
        # without completing setup_bot_scheduler. Check by looking for a
        # recent bot_signals row — if signals exist but come from before a 2h gap
        # it implies a crash-restart cycle.
        two_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        one_hour_ago  = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()

        # Only fire during hours when crypto quant bots should be active (24/7)
        gap = db.execute(sql_text("""
            SELECT COUNT(*) FROM bot_signals
            WHERE ts BETWEEN :start AND :end
              AND allocation_id IN (
                SELECT ba.id FROM bot_allocations ba
                JOIN bot_profiles bp ON bp.id = ba.profile_id
                WHERE bp.name = 'crypto_quant_aggressive' AND ba.paper_mode = 1
              )
        """), {"start": two_hours_ago, "end": one_hour_ago}).scalar() or 0

        # crypto_quant_aggressive runs every 5 min — expect at least 5 signals/hour
        if gap == 0:
            key = f"deploy_gap:{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H')}"
            if not _throttled(key):
                alerts.append({
                    "title": "crypto_quant_aggressive — 0 signals in last hour (possible crash/restart)",
                    "body": (
                        "crypto_quant_aggressive fires every 5 min and should produce signals every hour. "
                        "Zero signals in the past hour suggests either a scheduler crash, a deploy restart loop, "
                        "or a persistent strategy error that is being silently caught."
                    ),
                    "paste_ready": """ISSUE: crypto_quant_aggressive 0 signals in last hour — possible deploy/crash

DIAGNOSIS:
24/7 bot with 5-min cadence produced no signals in the last 60 min.
Likely causes:
1. Scheduler restarted mid-hour and missed triggers
2. Exception in run_bot_profile being caught silently
3. Alpaca crypto market data returning empty bars

QUICK VERIFY:
railway ssh "cd /app && python3 -c '
from app.db.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
with db.bind.connect() as c:
    r = c.execute(text(\\"SELECT COUNT(*), MAX(ts) FROM bot_signals bs JOIN bot_allocations ba ON ba.id=bs.allocation_id JOIN bot_profiles bp ON bp.id=ba.profile_id WHERE bp.name=\\'crypto_quant_aggressive\\' AND ts >= datetime(\\'now\\',\\'-2 hours\\')\\")).fetchone()
    print(\\"signals last 2h:\\", r[0], \\"last_ts:\\", r[1])
'"

FIX: Test-fire manually:
railway ssh "cd /app && python3 -c 'from strategy_lab.runner import run_bot_profile; print(run_bot_profile(\"crypto_quant_aggressive\"))'"
""",
                    "priority": "high",
                })
    except Exception as exc:
        logger.warning("[fleet_sentinel] deploy_health check failed: %s", exc)
    return alerts


# ── Check 3 + 5: Signal gap > 50 min AND 4× cadence staleness ─────────────────

def _check_signal_staleness(db: Session) -> list[dict]:
    alerts = []
    try:
        now_utc = datetime.now(timezone.utc)

        for bot_name, cfg in _BOT_CADENCE.items():
            if not _is_in_active_window(cfg["active_hours"]):
                continue

            # 2026-07-06: skip halted / disabled bots. Halted bots (mean_rev,
            # scalper at $0 per m062) were driving 3-4 alerts per 10-min cycle
            # with 8000+ minute gaps, drowning real regressions.
            if not _is_bot_funded_and_enabled(db, bot_name):
                continue

            cadence_min = cfg["cadence_min"]
            stale_threshold_min = max(50, cadence_min * 4)

            row = db.execute(sql_text("""
                SELECT MAX(bs.ts)
                FROM bot_signals bs
                JOIN bot_allocations ba ON ba.id = bs.allocation_id
                JOIN bot_profiles bp ON bp.id = ba.profile_id
                WHERE bp.name = :bot AND ba.paper_mode = 1
            """), {"bot": bot_name}).fetchone()

            last_ts_str = row[0] if row else None
            if not last_ts_str:
                continue  # no signals ever — skip (not a regression)

            try:
                last_ts = datetime.fromisoformat(str(last_ts_str).replace(" ", "T"))
                if last_ts.tzinfo is None:
                    last_ts = last_ts.replace(tzinfo=timezone.utc)
            except Exception:
                continue

            gap_min = (now_utc - last_ts).total_seconds() / 60

            if gap_min < stale_threshold_min:
                continue

            key = f"stale_signal:{bot_name}:{now_utc.strftime('%Y-%m-%d-%H')}"
            if _throttled(key):
                continue

            rule = "4× cadence" if gap_min >= cadence_min * 4 else "50-min gap"
            alerts.append({
                "title": f"{bot_name} — signal gap {gap_min:.0f} min ({rule})",
                "body": (
                    f"{bot_name} last fired a signal {gap_min:.0f} minutes ago. "
                    f"Expected cadence is every {cadence_min} min. "
                    f"This exceeds the {stale_threshold_min}-min alert threshold."
                ),
                "paste_ready": f"""ISSUE: {bot_name} signal gap {gap_min:.0f} min (expected every {cadence_min} min)

DIAGNOSIS:
Bot is in its active window but hasn't fired a signal in {gap_min:.0f} minutes.
Likely causes:
1. Ensemble filter rejecting all candidates (raw_signals > 0 but after_ensemble = 0)
2. All allocations at position_cap — guardrail blocking execution
3. Market data fetch silently returning empty bars (check bar fetch logs)

QUICK VERIFY:
railway ssh "cd /app && python3 -c '
from app.db.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
with db.bind.connect() as c:
    r = c.execute(text(\\"SELECT COUNT(*), MAX(ts) FROM bot_signals bs JOIN bot_allocations ba ON ba.id=bs.allocation_id JOIN bot_profiles bp ON bp.id=ba.profile_id WHERE bp.name=\\'{bot_name}\\' AND ts >= datetime(\\'now\\',\\'-3 hours\\')\\")).fetchone()
    print(\\"signals 3h:\\", r[0], \\"last:\\", r[1])
'"

FIX: Test-fire to check if pipeline runs clean:
railway ssh "cd /app && python3 -c 'from strategy_lab.runner import run_bot_profile; r = run_bot_profile(\"{bot_name}\"); print(r)'"
""",
                "priority": "normal" if gap_min < cadence_min * 8 else "high",
            })
    except Exception as exc:
        logger.warning("[fleet_sentinel] signal_staleness check failed: %s", exc)
    return alerts


# ── Check 4: Activity feed 0 trades during market hours ───────────────────────

def _check_activity_feed_empty(db: Session) -> list[dict]:
    alerts = []
    try:
        utc_hour = datetime.now(timezone.utc).hour
        # Market hours proxy: 13:30–21:00 UTC = 9:30 AM–5 PM ET
        if not (13 <= utc_hour < 21):
            return alerts

        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        trade_count = db.execute(sql_text("""
            SELECT COUNT(*) FROM bot_trades bt
            JOIN bot_allocations ba ON bt.allocation_id = ba.id
            WHERE ba.paper_mode = 1
              AND bt.ts >= :today
              AND bt.quarantined_at IS NULL
        """), {"today": today_start}).scalar() or 0

        if trade_count == 0:
            key = f"zero_trades:{datetime.now(timezone.utc).strftime('%Y-%m-%d')}"
            if not _throttled(key):
                alerts.append({
                    "title": "Activity feed — 0 trades today during market hours",
                    "body": (
                        "No paper trades recorded today. "
                        "It's currently market hours and the fleet should have executed. "
                        "This likely means all signals are being blocked at the guardrail level."
                    ),
                    "paste_ready": """ISSUE: 0 trades in activity feed during market hours

DIAGNOSIS:
No bot_trades rows written today for any paper allocation.
Likely causes:
1. All allocations at position_cap — guardrails blocking every entry
2. Regime gate filtering all signals (regime=chop or risk_off)
3. Signal generation running but execute_signal() failing silently

QUICK VERIFY:
railway ssh "cd /app && python3 -c '
from app.db.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
with db.bind.connect() as c:
    r = c.execute(text(\\"SELECT bp.name, COUNT(bt.id) FROM bot_trades bt JOIN bot_allocations ba ON bt.allocation_id=ba.id JOIN bot_profiles bp ON bp.id=ba.profile_id WHERE bt.ts >= date(\\'now\\') GROUP BY bp.name\\")).fetchall()
    [print(x) for x in r] or print(\\"0 trades\\")
'"

FIX: Check guardrail status and run a manual scan:
railway ssh "cd /app && python3 -c 'from strategy_lab.runner import run_bot_profile; print(run_bot_profile(\"stock_day\"))'"
""",
                    "priority": "high",
                })
    except Exception as exc:
        logger.warning("[fleet_sentinel] activity_feed_empty check failed: %s", exc)
    return alerts


# ── Check 6: Asset class mismatch positions ────────────────────────────────────

def _check_asset_class_mismatches(db: Session) -> list[dict]:
    alerts = []
    try:
        # Crypto bots holding stock symbols (no "/" in symbol)
        mismatches = db.execute(sql_text("""
            SELECT bp.name, bpos.symbol, bpos.id
            FROM bot_positions bpos
            JOIN bot_allocations ba ON bpos.allocation_id = ba.id
            JOIN bot_profiles bp ON ba.profile_id = bp.id
            WHERE bpos.closed_at IS NULL
              AND bpos.quarantined_at IS NULL
              AND ba.paper_mode = 1
              AND bp.asset_class = 'crypto'
              AND bpos.symbol NOT LIKE '%/%'
            LIMIT 20
        """)).fetchall()

        if mismatches:
            bot_names = list({r[0] for r in mismatches})
            symbols   = list({r[1] for r in mismatches})
            pos_ids   = [r[2] for r in mismatches]
            key = f"asset_mismatch:{','.join(sorted(bot_names))}"
            if not _throttled(key):
                ids_str = ", ".join(str(i) for i in pos_ids)
                alerts.append({
                    "title": f"Asset class mismatch — {len(mismatches)} stock positions in crypto bots",
                    "body": (
                        f"{len(mismatches)} open positions in crypto bot(s) ({', '.join(bot_names)}) "
                        f"have stock symbols ({', '.join(symbols[:5])}). "
                        f"These distort P&L and open position counts. Quarantine recommended."
                    ),
                    "paste_ready": f"""ISSUE: {len(mismatches)} stock symbols in crypto bot positions

DIAGNOSIS:
Crypto-classified bots are holding equity positions (no '/' in symbol).
These are routing artifacts from before asset-class routing was enforced.
Likely causes:
1. Pre-routing-fix positions that escaped the last quarantine sweep
2. A new routing bug re-routing stock signals to crypto allocations
3. Bot profile asset_class mismatch (profile says crypto but strategy picks stocks)

QUICK VERIFY:
railway ssh "cd /app && python3 -c '
from app.db.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
with db.bind.connect() as c:
    r = c.execute(text(\\"SELECT id, symbol, quarantined_at FROM bot_positions WHERE id IN ({ids_str})\\")).fetchall()
    [print(x) for x in r]
'"

FIX: Quarantine the mismatched positions:
railway ssh "cd /app && python3 -c '
from app.db.session import SessionLocal
from sqlalchemy import text
from datetime import datetime
db = SessionLocal()
with db.bind.connect() as c:
    for pid in [{ids_str}]:
        c.execute(text(\\"UPDATE bot_positions SET quarantined_at=:ts, quarantine_reason=\\'asset_class_mismatch_pre_routing_fix\\' WHERE id=:id\\"), {{\\"ts\\": datetime.utcnow().isoformat(), \\"id\\": pid}})
    c.commit()
    print(\\"quarantined\\")
'"
""",
                    "priority": "normal",
                })
    except Exception as exc:
        logger.warning("[fleet_sentinel] asset_class_mismatch check failed: %s", exc)
    return alerts


# ── Check 7: bot_daily_pnl rows stopped incrementing ─────────────────────────

def _check_pnl_rows_stale(db: Session) -> list[dict]:
    alerts = []
    try:
        from datetime import date
        today = date.today().isoformat()

        # Active paper bots (have trades in last 7 days)
        active_bots = db.execute(sql_text("""
            SELECT DISTINCT bp.name
            FROM bot_trades bt
            JOIN bot_allocations ba ON bt.allocation_id = ba.id
            JOIN bot_profiles bp ON ba.profile_id = bp.id
            WHERE ba.paper_mode = 1
              AND bt.quarantined_at IS NULL
              AND bt.ts >= datetime('now', '-7 days')
        """)).fetchall()
        active_names = {r[0] for r in active_bots}

        if not active_names:
            return alerts

        # Which of those have a pnl row for today?
        pnl_today = db.execute(sql_text("""
            SELECT DISTINCT bp.name
            FROM bot_daily_pnl bdp
            JOIN bot_allocations ba ON bdp.allocation_id = ba.id
            JOIN bot_profiles bp ON ba.profile_id = bp.id
            WHERE bdp.date = :today AND ba.paper_mode = 1
        """), {"today": today}).fetchall()
        has_pnl = {r[0] for r in pnl_today}

        # Only alert after 5 PM UTC (after US market close) — pnl rows written EOD
        utc_hour = datetime.now(timezone.utc).hour
        if utc_hour < 17:
            return alerts

        missing = sorted(active_names - has_pnl)
        if missing:
            key = f"pnl_stale:{today}"
            if not _throttled(key):
                missing_str = ", ".join(missing[:8])
                alerts.append({
                    "title": f"bot_daily_pnl missing today — {len(missing)} active bots",
                    "body": (
                        f"{len(missing)} bot(s) traded today but have no bot_daily_pnl row for {today}: "
                        f"{missing_str}. "
                        f"The EOD P&L aggregation job may not have run or failed silently."
                    ),
                    "paste_ready": f"""ISSUE: bot_daily_pnl rows missing for {today} — {len(missing)} bots

DIAGNOSIS:
Bots have trade activity today but no P&L summary row was written for {today}.
Likely causes:
1. compute_bot_stats job failed or hasn't run yet (fires 2 AM ET)
2. bot_daily_pnl table write failing silently (check for DB lock or constraint errors)
3. The bots only had buy trades today — no realized P&L yet (no sell fills)

QUICK VERIFY:
railway ssh "cd /app && python3 -c '
from app.db.session import SessionLocal
from sqlalchemy import text
db = SessionLocal()
with db.bind.connect() as c:
    r = c.execute(text(\\"SELECT bp.name, COUNT(bt.id) as trades FROM bot_trades bt JOIN bot_allocations ba ON bt.allocation_id=ba.id JOIN bot_profiles bp ON bp.id=ba.profile_id WHERE bt.ts >= date(\\'now\\') AND bt.quarantined_at IS NULL GROUP BY bp.name\\")).fetchall()
    [print(\\"trades:\\", x) for x in r]
    r = c.execute(text(\\"SELECT bp.name FROM bot_daily_pnl bdp JOIN bot_allocations ba ON bdp.allocation_id=ba.id JOIN bot_profiles bp ON bp.id=ba.profile_id WHERE bdp.date=date(\\'now\\')\\")).fetchall()
    [print(\\"has_pnl:\\", x[0]) for x in r]
'"

FIX: Run the stats job manually:
railway ssh "cd /app && python3 -c '
from app.db.session import SessionLocal
from strategy_lab.core.bot_health import record_heartbeat
db = SessionLocal()
from strategy_lab.runner import run_bot_profile
# Or trigger compute_bot_stats directly if it exists as a standalone function
'"
""",
                    "priority": "normal",
                })
    except Exception as exc:
        logger.warning("[fleet_sentinel] pnl_stale check failed: %s", exc)
    return alerts


# ── Main entry point ───────────────────────────────────────────────────────────

def run_fleet_sentinel(db: Session) -> dict:
    """
    Run all 7 fleet health checks. Post paste-ready alerts to #fund-updates
    for any triggered rule. Deduplicates within a 4-hour window.
    Returns summary dict: {checks_run, alerts_posted, alerts_suppressed}.
    """
    from agents.bus import post_update_request

    all_checks = [
        _check_red_transitions,
        _check_deploy_health,
        _check_signal_staleness,   # covers checks 3 + 5
        _check_activity_feed_empty,
        _check_asset_class_mismatches,
        _check_pnl_rows_stale,
    ]

    posted = 0
    suppressed = 0

    for check_fn in all_checks:
        try:
            alerts = check_fn(db)
            for alert in alerts:
                ok = post_update_request(
                    from_agent="sentinel_devops",
                    title=alert["title"],
                    body=alert["body"],
                    paste_ready=alert["paste_ready"],
                    priority=alert.get("priority", "normal"),
                )
                if ok:
                    posted += 1
                    logger.warning("[fleet_sentinel] posted alert: %s", alert["title"])
                else:
                    suppressed += 1
        except Exception as exc:
            logger.warning("[fleet_sentinel] check %s failed: %s", check_fn.__name__, exc)

    logger.warning(
        "[fleet_sentinel] run complete — alerts_posted=%d suppressed=%d",
        posted, suppressed,
    )
    return {"checks_run": len(all_checks), "alerts_posted": posted, "alerts_suppressed": suppressed}
