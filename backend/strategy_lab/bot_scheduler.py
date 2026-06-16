"""APScheduler integration for the six bot profiles.

setup_bot_scheduler(scheduler) is called from app/main.py lifespan,
after setup_monitoring_scheduler, using the same AsyncIOScheduler instance.
"""
from __future__ import annotations

import logging
from datetime import datetime

import pytz
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
UTC = pytz.utc


def _run_bot_position_monitor(bot_name: str) -> None:
    try:
        from strategy_lab.core.position_monitor import monitor_bot_positions
        monitor_bot_positions(bot_name)
    except Exception as exc:
        logger.error("bot_position_monitor[%s] failed: %s", bot_name, exc)


def _run_and_log(profile_name: str) -> None:
    """Thin wrapper so APScheduler job invocations appear in Railway logs."""
    logger.warning("[scheduled] %s scan START", profile_name)
    from app.db.session import SessionLocal
    from strategy_lab.scan_and_execute import scan_and_execute
    db = SessionLocal()
    try:
        result = scan_and_execute(profile_name, db, persist=True, execute=True)
        logger.warning(
            "[scheduled] %s scan DONE — signals=%d trades=%d errors=%d",
            profile_name,
            result.get("signals_generated", 0),
            result.get("trades_executed", 0),
            len(result.get("errors", [])),
        )
    except Exception as exc:
        logger.error("[scheduled] %s FAILED: %s", profile_name, exc, exc_info=True)
    finally:
        db.close()


def setup_bot_scheduler(scheduler) -> None:
    """Register the six bot-profile cron jobs.

    Schedule reference (all times ET unless noted):
      stock_swing  — weekdays 4:05 PM ET (market close + 5 min)
      stock_lt     — first Tuesday of each month, 10:00 AM ET
      crypto_swing — every 4 hours (24/7)
      crypto_lt    — Monday 10:00 AM UTC (weekly DCA)
    """
    logger.warning("[startup-trace] setup_bot_scheduler called — registering bot jobs")
    from strategy_lab.runner import run_bot_profile

    # ------------------------------------------------------------------
    # stock_swing: 4:05 PM ET, Mon-Fri
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("stock_swing"),
        CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=ET),
        id="bot_stock_swing",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # stock_day: intraday — every 5 min during market hours, Mon-Fri
    # (opening-range established after first 30 min)
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("stock_day"),
        CronTrigger(day_of_week="mon-fri", hour="4-19", minute="*/5", timezone=ET),
        id="bot_stock_day",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # stock_lt: every Tuesday 10:00 AM ET (was: first Tue of month)
    # Weekly cadence keeps the UI alive for demo; the strategy itself
    # still only rebalances when factor signals change significantly.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("stock_lt"),
        CronTrigger(day_of_week="tue", hour=10, minute=0, timezone=ET),
        id="bot_stock_lt",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # crypto_swing: every 4 hours, 24/7 — fire immediately on startup
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_swing"),
        CronTrigger(hour="*/4", minute=0),
        id="bot_crypto_swing",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_day: every 5 min, 24/7 — crypto has no market-hours gate
    # Reduced from 1min: each scan takes 15-30s; 1min with max_instances=1
    # meant every 10s Alpaca timeout dropped the next trigger permanently.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_day"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_day",
        replace_existing=True,
        next_run_time=datetime.now(UTC),  # fire immediately on startup
        max_instances=1,
        misfire_grace_time=300,  # tolerate up to 5 min startup lag before skipping
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_lt DCA: Monday 10:00 AM UTC
    # next_run_time=datetime.now(UTC) fires once on startup so we get a
    # health record immediately without waiting until next Monday.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_lt"),
        CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=UTC),
        id="bot_crypto_lt_dca",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # v2 LEAN framework — crypto_lt shadow runner (same schedule as v1)
    # Runs side-by-side: writes to v2_shadow_runs, no trade execution.
    # Compare output with v1 bot_signals to validate parity before cutover.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: __import__("strategy_lab.v2.shadow_runner", fromlist=["run_v2_shadow"]).run_v2_shadow("crypto_lt"),
        CronTrigger(day_of_week="mon", hour=10, minute=1, timezone=UTC),  # 1 min after v1
        id="bot_crypto_lt_v2_shadow",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Daily briefing email: 8:00 AM ET, Mon-Fri
    # ------------------------------------------------------------------
    def _run_daily_briefing():
        from app.db.session import SessionLocal
        from strategy_lab.daily_briefing import run_daily_briefing_job

        db = SessionLocal()
        try:
            run_daily_briefing_job(db)
        except Exception as exc:
            logger.error("daily_briefing job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_daily_briefing,
        CronTrigger(day_of_week="mon-fri", hour=8, minute=0, timezone=ET),
        id="daily_briefing_email",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Position monitor: every 2 minutes, 24/7
    # Checks open positions against stop/target; handles trailing stop.
    # ------------------------------------------------------------------
    def _run_position_monitor():
        try:
            from strategy_lab.core.position_monitor import run_position_monitor
            run_position_monitor()
        except Exception as exc:
            logger.error("position_monitor job failed: %s", exc)

    scheduler.add_job(
        _run_position_monitor,
        CronTrigger(minute="*/2"),
        id="position_monitor",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=120,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # stock_day intraday position monitor: every 5 min, 4am–7pm ET, Mon-Fri
    # Extended to cover premarket + afterhours positions.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_bot_position_monitor("stock_day"),
        CronTrigger(day_of_week="mon-fri", hour="4-19", minute="*/5", timezone=ET),
        id="bot_stock_day_position_monitor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # stock_swing intraday position monitor: every 5 min, 9–15 ET, Mon-Fri
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_bot_position_monitor("stock_swing"),
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=ET),
        id="bot_stock_swing_position_monitor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # Dead-man's switch: every hour during market hours, Mon-Fri
    # (check_dead_mans_switch itself gates on 9:30–16:00 ET)
    # ------------------------------------------------------------------
    def _run_dead_mans_switch():
        from app.db.session import SessionLocal
        from strategy_lab.core.bot_health import check_dead_mans_switch

        db = SessionLocal()
        try:
            check_dead_mans_switch(db, lookback_hours=4)
        except Exception as exc:
            logger.error("dead_mans_switch job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_dead_mans_switch,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute=0, timezone=ET),
        id="dead_mans_switch",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # crypto_onchain: every 4 hours, 24/7 (same cadence as crypto_swing)
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_onchain"),
        CronTrigger(hour="*/4", minute=30),
        id="bot_crypto_onchain",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # options_income: every 30 min during market hours, Mon-Fri
    # Scans high-IV stocks for wheel / covered-call / CSP entries.
    # Starts at 10:00 AM (after opening range) through 3:30 PM.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("options_income"),
        CronTrigger(day_of_week="mon-fri", hour="10-15", minute="0,30", timezone=ET),
        id="bot_options_income",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # options_directional: every 30 min during market hours, Mon-Fri
    # Scans for credit/debit spreads and momentum options entries.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("options_directional"),
        CronTrigger(day_of_week="mon-fri", hour="10-15", minute="0,30", timezone=ET),
        id="bot_options_directional",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=900,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_quant_aggressive: every 5 min, 24/7
    # High-turnover quant bot — 20-coin universe, 5-signal stack.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_aggressive"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_quant_aggressive",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_aggressive (*/5 min, fires immediately)")

    # ------------------------------------------------------------------
    # crypto_quant_aggressive: end-of-day summary to #quant-signals at 23:55 UTC
    # ------------------------------------------------------------------
    def _cqa_eod_summary():
        try:
            from app.services.discord_public import post_signal
            from app.db.session import SessionLocal
            from app.db.models.bots import BotSignal, BotAllocation, BotProfile
            from datetime import date
            from sqlalchemy import func
            db = SessionLocal()
            try:
                prof = db.query(BotProfile).filter(BotProfile.name == "crypto_quant_aggressive").first()
                if not prof:
                    return
                today = date.today()
                sigs = (
                    db.query(BotSignal)
                    .join(BotAllocation, BotSignal.allocation_id == BotAllocation.id)
                    .filter(
                        BotAllocation.profile_id == prof.id,
                        func.date(BotSignal.ts) == today,
                    )
                    .all()
                )
                buys = sum(1 for s in sigs if s.side == "buy")
                sells = sum(1 for s in sigs if s.side == "sell")
                symbols = list({s.symbol for s in sigs})[:8]
                summary_signal = {
                    "bot": "crypto_quant_aggressive",
                    "symbol": "PORTFOLIO",
                    "side": "hold",
                    "strategy": "EOD_SUMMARY",
                    "reason": (
                        f"End-of-day summary — Crypto Quant Aggressive\n"
                        f"Signals today: {len(sigs)} ({buys} long, {sells} short)\n"
                        f"Symbols: {', '.join(symbols) or 'none'}\n"
                        f"Paper trading. Not investment advice. Not a registered investment adviser."
                    ),
                    "confidence": 1.0,
                    "price": None,
                    "size_pct": None,
                    "stop": None,
                    "target": None,
                }
                post_signal(summary_signal)
            finally:
                db.close()
        except Exception as exc:
            logger.error("cqa_eod_summary failed: %s", exc)

    scheduler.add_job(
        _cqa_eod_summary,
        CronTrigger(hour=23, minute=55, timezone=UTC),
        id="cqa_eod_summary",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # crypto_quant_scalper: every 1 min, 24/7
    # 1m scalper — tight R/R, liquid majors only.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_scalper"),
        CronTrigger(minute="*/1"),
        id="bot_crypto_quant_scalper",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=120,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_scalper (*/1 min, fires immediately)")

    # ------------------------------------------------------------------
    # crypto_quant_mean_reversion: every 3 min, 24/7
    # 5m mean-reversion bot — 4h holds, wider stops.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_quant_mean_reversion"),
        CronTrigger(minute="*/3"),
        id="bot_crypto_quant_mean_reversion",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=180,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job bot_crypto_quant_mean_reversion (*/3 min, fires immediately)")

    # One-time startup log: emit cooldown_minutes for each quant bot so Railway
    # logs confirm the YAML setting is in effect on this deploy.
    try:
        from strategy_lab.seeds import load_profile as _lp
        for _pname in ("crypto_quant_scalper", "crypto_quant_aggressive", "crypto_quant_mean_reversion"):
            _p = _lp(_pname) or {}
            logger.warning(
                "[cooldown-active] bot=%s cadence=%s cooldown_minutes=%s position_cap=%s",
                _pname, _p.get("cadence", "?"), _p.get("cooldown_minutes", 0), _p.get("position_cap", "?"),
            )
    except Exception as _exc:
        logger.warning("[cooldown-active] could not load profiles: %s", _exc)

    # ------------------------------------------------------------------
    # Public Discord daily digest: 4:30 PM ET weekdays + midnight UTC (crypto)
    # ------------------------------------------------------------------
    def _discord_daily_digest():
        try:
            from app.services.discord_public import post_daily_digest
            from app.db.session import SessionLocal
            from app.db.models.bots import BotSignal, BotDailyPnL
            from datetime import date
            db = SessionLocal()
            try:
                today = date.today()
                from sqlalchemy import func
                sigs = db.query(BotSignal).filter(
                    func.date(BotSignal.ts) == today
                ).all()
                by_bot: dict = {}
                for s in sigs:
                    from app.db.models.bots import BotAllocation, BotProfile
                    alloc = db.get(BotAllocation, s.allocation_id)
                    if alloc:
                        prof = db.get(BotProfile, alloc.profile_id)
                        if prof:
                            by_bot[prof.name] = by_bot.get(prof.name, 0) + 1
                top_syms = list({s.symbol for s in sigs})[:5]
                pnl_rows = db.query(BotDailyPnL).filter(BotDailyPnL.date == today).all()
                realized = sum(r.realized_cents for r in pnl_rows)
                post_daily_digest({
                    "total_signals": len(sigs),
                    "by_bot": by_bot,
                    "top_symbols": top_syms,
                    "realized_pnl_cents": realized,
                })
            finally:
                db.close()
        except Exception as exc:
            logger.error("discord daily digest failed: %s", exc)

    scheduler.add_job(
        _discord_daily_digest,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ET),
        id="discord_daily_digest",
        replace_existing=True,
    )
    scheduler.add_job(
        _discord_daily_digest,
        CronTrigger(hour=0, minute=5, timezone=UTC),  # midnight UTC for crypto
        id="discord_daily_digest_crypto",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Weekly leaderboard: Sundays 6 PM ET
    # ------------------------------------------------------------------
    def _discord_weekly_leaderboard():
        try:
            from app.services.discord_public import post_weekly_leaderboard
            from app.db.session import SessionLocal
            db = SessionLocal()
            try:
                from app.core.canonical import compute_strategy_lab_aggregate
                from app.db.models.users import User
                users = db.query(User).filter(User.is_active.is_(True)).limit(1).all()
                if users:
                    result = compute_strategy_lab_aggregate(users[0].id, db)
                    post_weekly_leaderboard(result.get("leaderboard", []))
            finally:
                db.close()
        except Exception as exc:
            logger.error("discord weekly leaderboard failed: %s", exc)

    scheduler.add_job(
        _discord_weekly_leaderboard,
        CronTrigger(day_of_week="sun", hour=18, minute=0, timezone=ET),
        id="discord_weekly_leaderboard",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Monthly recap: 1st of month, 9:00 AM ET
    # ------------------------------------------------------------------
    def _discord_monthly_recap():
        try:
            from app.services.discord_public import post_monthly_recap
            from app.db.session import SessionLocal
            from app.db.models.bots import BotSignal, BotDailyPnL, BotTrade
            from datetime import date
            import calendar

            db = SessionLocal()
            try:
                today      = date.today()
                # Previous month bounds
                first_prev = date(today.year, today.month - 1 if today.month > 1 else 12, 1)
                if today.month == 1:
                    first_prev = date(today.year - 1, 12, 1)
                else:
                    first_prev = date(today.year, today.month - 1, 1)
                last_prev  = date(first_prev.year, first_prev.month,
                                  calendar.monthrange(first_prev.year, first_prev.month)[1])
                from sqlalchemy import func
                signals = db.query(BotSignal).filter(
                    func.date(BotSignal.ts) >= first_prev,
                    func.date(BotSignal.ts) <= last_prev,
                ).count()
                pnl_rows = db.query(BotDailyPnL).filter(
                    BotDailyPnL.date >= first_prev,
                    BotDailyPnL.date <= last_prev,
                ).all()
                pnl_cents = sum(
                    (r.realized_cents or 0) + (r.unrealized_cents or 0)
                    for r in pnl_rows
                )
                trades = db.query(BotTrade).filter(
                    BotTrade.side == "sell",
                    func.date(BotTrade.ts) >= first_prev,
                    func.date(BotTrade.ts) <= last_prev,
                ).count()
                post_monthly_recap({
                    "month_name": first_prev.strftime("%B %Y"),
                    "signals":    signals,
                    "trades":     trades,
                    "pnl_cents":  pnl_cents,
                })
            finally:
                db.close()
        except Exception as exc:
            logger.error("discord monthly recap failed: %s", exc)

    scheduler.add_job(
        _discord_monthly_recap,
        CronTrigger(day=1, hour=9, minute=0, timezone=ET),
        id="discord_monthly_recap",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Recurring dupe quarantine: every 10 min, 24/7
    # Band-aid until cooldown root cause is confirmed fixed. Same logic
    # as the startup migration but runs repeatedly so dupes can't
    # accumulate between restarts.
    # ------------------------------------------------------------------
    def _quarantine_dupes_periodic():
        try:
            from app.db.session import SessionLocal
            from sqlalchemy import text
            from datetime import datetime as _dt, timezone as _tz
            from collections import defaultdict as _dd

            db = SessionLocal()
            try:
                rows = db.execute(text("""
                    SELECT id, allocation_id, symbol, avg_cost_cents, qty, opened_at
                    FROM bot_positions
                    WHERE closed_at IS NULL
                      AND quarantined_at IS NULL
                    ORDER BY allocation_id, symbol, id
                """)).fetchall()

                groups = _dd(list)
                for row in rows:
                    groups[(row[1], row[2])].append({
                        "id": row[0], "avg_cost_cents": row[3] or 0,
                        "qty": row[4] or 0, "opened_at": row[5],
                    })

                def _ts(s):
                    if not s:
                        return 0
                    try:
                        if isinstance(s, _dt):
                            return int(s.timestamp())
                        return int(_dt.fromisoformat(str(s).replace("Z", "+00:00")).timestamp())
                    except Exception:
                        return 0

                to_quarantine = []
                for positions in groups.values():
                    if len(positions) < 2:
                        continue
                    sorted_pos = sorted(positions, key=lambda x: x["id"])
                    keeper = sorted_pos[0]
                    keeper_ts = _ts(keeper["opened_at"])
                    for pos in sorted_pos[1:]:
                        same_cost = abs(pos["avg_cost_cents"] - keeper["avg_cost_cents"]) <= 1
                        same_qty = abs(pos["qty"] - keeper["qty"]) < 0.0001
                        within_60s = abs(_ts(pos["opened_at"]) - keeper_ts) <= 60
                        if same_cost and same_qty and within_60s:
                            to_quarantine.append(pos["id"])

                if to_quarantine:
                    now = _dt.now(_tz.utc).isoformat()
                    for pos_id in to_quarantine:
                        db.execute(text("""
                            UPDATE bot_positions
                            SET quarantined_at = :now,
                                quarantine_reason = 'cooldown_dupe_merged'
                            WHERE id = :id
                        """), {"now": now, "id": pos_id})
                    db.commit()
                    logger.error(
                        "[dupe-quarantine] periodic: quarantined %d duplicate positions",
                        len(to_quarantine),
                    )
                else:
                    logger.warning("[dupe-quarantine] periodic: no duplicates found")
            finally:
                db.close()
        except Exception as exc:
            logger.error("[dupe-quarantine] periodic job failed: %s", exc)

    scheduler.add_job(
        _quarantine_dupes_periodic,
        CronTrigger(minute="*/10"),
        id="quarantine_dupes_periodic",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    def _post_discord_daily_digest(db) -> None:
        from strategy_lab.daily_briefing import build_discord_digest
        from app.services.discord_public import post_daily_digest
        try:
            digest = build_discord_digest(db)
            post_daily_digest(digest)
            logger.warning(
                "[daily-digest] posted — signals=%d pnl_cents=%d open=%d",
                digest["total_signals"], digest["realized_pnl_cents"], digest["open_positions"],
            )
        except Exception as exc:
            logger.error("[daily-digest] build/post failed: %s", exc)

    # ------------------------------------------------------------------
    # Daily Discord digest: 4:30 PM ET, Mon-Fri (after stock market close)
    # Posts P&L summary, top trades, signal count to #daily-digest.
    # ------------------------------------------------------------------
    def _run_daily_discord_digest():
        from app.db.session import SessionLocal
        db = SessionLocal()
        try:
            _post_discord_daily_digest(db)
        except Exception as exc:
            logger.error("daily_discord_digest job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_daily_discord_digest,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=ET),
        id="daily_discord_digest",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # Strategy Scout scanner: every 5 min — gate on ENABLE_STRATEGY_SCOUT.
    # ------------------------------------------------------------------
    def _run_scout_scan():
        try:
            from strategy_lab.scout_scanner import run_scout_scan
            run_scout_scan()
        except Exception as exc:
            logger.error("[scout-scanner] job failed: %s", exc)

    scheduler.add_job(
        _run_scout_scan,
        CronTrigger(minute="*/5"),
        id="strategy_scout_scan",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # The Forge scanner: every 5 min — gate on ENABLE_STRATEGY_FORGE.
    # ------------------------------------------------------------------
    def _run_forge_scan():
        try:
            from strategy_lab.forge_scanner import run_forge_scan
            run_forge_scan()
        except Exception as exc:
            logger.error("[forge-scanner] job failed: %s", exc)

    scheduler.add_job(
        _run_forge_scan,
        CronTrigger(minute="*/5"),
        id="strategy_forge_scan",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=60,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # Signal explanation pre-gen: hourly — gate on ENABLE_TRADE_EXPLAIN.
    # ------------------------------------------------------------------
    def _run_explain_pregen():
        import os
        if os.getenv("ENABLE_TRADE_EXPLAIN", "false").strip().lower() != "true":
            return
        try:
            from strategy_lab.explain_pregen import run_explain_pregen
            run_explain_pregen()
        except Exception as exc:
            logger.error("[explain-pregen] job failed: %s", exc)

    scheduler.add_job(
        _run_explain_pregen,
        CronTrigger(minute=30),
        id="signal_explain_pregen",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # tsmom_multi_asset: Friday 5PM ET weekly rebalance
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("tsmom_multi_asset"),
        CronTrigger(day_of_week="fri", hour=17, minute=0, timezone=ET),
        id="bot_tsmom_multi_asset",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # quality_factor: first Tuesday of month 10:30 AM ET
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("quality_factor"),
        CronTrigger(day_of_week="tue", hour=10, minute=30, timezone=ET),
        id="bot_quality_factor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # value_quality: first Tuesday of month 11 AM ET
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("value_quality"),
        CronTrigger(day_of_week="tue", hour=11, minute=0, timezone=ET),
        id="bot_value_quality",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # crypto_meanrev_2163: every 4 hours, 24/7
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: _run_and_log("crypto_meanrev_2163"),
        CronTrigger(hour="*/4", minute=30),
        id="bot_crypto_meanrev_2163",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # earnings_nlp: 9AM ET daily Mon-Fri (BLOCKED stub)
    # ------------------------------------------------------------------
    def _earnings_nlp_guarded():
        if not os.getenv("ENABLE_EARNINGS_NLP"):
            return
        _run_and_log("earnings_nlp")

    scheduler.add_job(
        _earnings_nlp_guarded,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=ET),
        id="bot_earnings_nlp",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
    )

    # ------------------------------------------------------------------
    # Bot performance stats rollup: 2:00 AM ET daily
    # ------------------------------------------------------------------
    def _run_compute_bot_stats():
        try:
            from app.jobs.compute_bot_stats import run as run_stats
            result = run_stats()
            logger.warning(
                "[compute-bot-stats] done — processed=%d promoted=%d demoted=%d errors=%d",
                result.get("processed", 0), result.get("promoted", 0),
                result.get("demoted", 0), result.get("errors", 0),
            )
        except Exception as exc:
            logger.error("[compute-bot-stats] failed: %s", exc)

    scheduler.add_job(
        _run_compute_bot_stats,
        CronTrigger(hour=2, minute=0, timezone=ET),
        id="compute_bot_stats",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job compute_bot_stats (2:00 AM ET daily)")

    # ------------------------------------------------------------------
    # Queen Agent — 4 posts per day to #dev-log
    #   morning  07:00 AM ET  Intelligence brief (regime, IC, directives)
    #   midday   12:00 PM ET  Intraday pulse (P&L so far, signals)
    #   close    04:30 PM ET  EOD report (full day P&L, winners/losers)
    #   evening  09:00 PM ET  Crypto/overnight watch (24/7 — covers crypto)
    # ------------------------------------------------------------------
    def _make_queen_job(session_name: str):
        def _job():
            from app.db.session import SessionLocal
            from strategy_lab.agents.queen import run_queen_daily
            db = SessionLocal()
            try:
                run_queen_daily(db, session=session_name)
            except Exception as exc:
                logger.error("[queen-%s] job failed: %s", session_name, exc)
            finally:
                db.close()
        _job.__name__ = f"_queen_{session_name}"
        return _job

    _queen_schedules = [
        ("morning",       dict(day_of_week="mon-fri", hour=7,  minute=0,  timezone=ET)),
        ("midday",        dict(day_of_week="mon-fri", hour=12, minute=0,  timezone=ET)),
        ("close",         dict(day_of_week="mon-fri", hour=16, minute=30, timezone=ET)),
        ("evening",       dict(hour=21, minute=0, timezone=ET)),
        ("weekend_recap", dict(day_of_week="mon", hour=6, minute=0, timezone=ET)),
        ("weekly",        dict(day_of_week="sun", hour=20, minute=0, timezone=ET)),
    ]
    for _session, _cron_kwargs in _queen_schedules:
        scheduler.add_job(
            _make_queen_job(_session),
            CronTrigger(**_cron_kwargs),
            id=f"queen_{_session}",
            replace_existing=True,
            max_instances=1,
            misfire_grace_time=1800,
            coalesce=True,
        )
        logger.warning("[startup-trace] registered job queen_%s", _session)

    # ------------------------------------------------------------------
    # Regime snapshot refresh — hourly, keeps regime_snapshots table fresh
    # so DQW, researcher, and queen always have current market regime data.
    # Fires immediately on startup to seed the table.
    # ------------------------------------------------------------------
    def _run_regime_refresh():
        from app.db.session import SessionLocal
        from strategy_lab.core.regime_detector import get_regime, _persist_snapshot
        db = SessionLocal()
        try:
            # get_regime() returns cached value if fresh — always force a DB persist
            regime = get_regime(db)
            _persist_snapshot(regime, db)  # _persist_snapshot has its own 15-min DB guard
            logger.info("[regime_refresh] snapshot updated: vix=%s trend=%s",
                        regime.get("vix_regime"), regime.get("trend_regime"))
        except Exception as exc:
            logger.error("[regime_refresh] failed: %s", exc)
        finally:
            db.close()

    from apscheduler.triggers.interval import IntervalTrigger as _IT
    from datetime import datetime as _dt, timezone as _tz
    scheduler.add_job(
        _run_regime_refresh,
        _IT(hours=1),
        id="regime_snapshot_refresh",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
        coalesce=True,
        next_run_time=_dt.now(_tz.utc),  # fire immediately on startup
    )
    logger.warning("[startup-trace] registered job regime_snapshot_refresh (hourly, fires now)")

    # ------------------------------------------------------------------
    # Regime alert check — event-driven, polls every 30 min
    # Posts immediately to Discord when a condition fires (24h cooldown).
    # ------------------------------------------------------------------
    def _run_regime_alert_check():
        from app.db.session import SessionLocal
        from strategy_lab.agents.queen import run_regime_alert_check
        db = SessionLocal()
        try:
            run_regime_alert_check(db)
        except Exception as exc:
            logger.error("[queen-regime-alert] failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_regime_alert_check,
        CronTrigger(minute="*/30"),
        id="queen_regime_alert_check",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job queen_regime_alert_check (every 30 min)")

    # ------------------------------------------------------------------
    # Deploy 2 — Tier A monitor agents
    # ------------------------------------------------------------------

    # Risk Sentinel: every 30 min — fleet drawdown + consecutive loss watchdog
    def _run_risk_sentinel():
        from app.db.session import SessionLocal
        from strategy_lab.agents.risk_sentinel import run_risk_health_check
        db = SessionLocal()
        try:
            run_risk_health_check(db)
        except Exception as exc:
            logger.error("[risk_sentinel] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_risk_sentinel,
        CronTrigger(minute="*/30"),
        id="risk_sentinel",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=600,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job risk_sentinel (every 30 min, fires immediately)")

    # Data Quality Watcher: every hour — regime snapshot + signal freshness
    def _run_data_quality_watcher():
        from app.db.session import SessionLocal
        from strategy_lab.agents.data_quality_watcher import run_data_quality_check
        db = SessionLocal()
        try:
            run_data_quality_check(db)
        except Exception as exc:
            logger.error("[data_quality_watcher] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_data_quality_watcher,
        CronTrigger(minute=0),
        id="data_quality_watcher",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job data_quality_watcher (hourly, fires immediately)")

    # Execution Auditor: 5 PM ET Mon-Fri — fill quality + slippage after market close
    def _run_execution_auditor():
        from app.db.session import SessionLocal
        from strategy_lab.agents.execution_auditor import run_execution_audit
        db = SessionLocal()
        try:
            run_execution_audit(db)
        except Exception as exc:
            logger.error("[execution_auditor] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_execution_auditor,
        CronTrigger(day_of_week="mon-fri", hour=17, minute=0, timezone=ET),
        id="execution_auditor",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job execution_auditor (5 PM ET Mon-Fri)")

    # Operations: 6 PM ET Mon-Fri — back-office reconciliation after execution audit
    def _run_operations():
        from app.db.session import SessionLocal
        from strategy_lab.agents.operations import run_operations_reconciliation
        db = SessionLocal()
        try:
            run_operations_reconciliation(db)
        except Exception as exc:
            logger.error("[operations] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_operations,
        CronTrigger(day_of_week="mon-fri", hour=18, minute=0, timezone=ET),
        id="operations",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job operations (6 PM ET Mon-Fri)")

    # ------------------------------------------------------------------
    # Daily standup: 7:00 AM ET — all agents contribute, Queen synthesizes plan
    # Fires immediately on startup so we get a first plan without waiting.
    # ------------------------------------------------------------------
    def _run_daily_standup():
        from app.db.session import SessionLocal
        from agents.standup import run_daily_standup
        db = SessionLocal()
        try:
            run_daily_standup(db)
        except Exception as exc:
            logger.error("[daily_standup] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_daily_standup,
        CronTrigger(hour=7, minute=0, timezone=ET),
        id="daily_standup",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job daily_standup (7 AM ET, fires immediately)")

    # ------------------------------------------------------------------
    # Macro Strategist: 7:05 AM ET daily — classify regime after standup
    # ------------------------------------------------------------------
    def _run_macro_classification():
        from app.db.session import SessionLocal
        from strategy_lab.agents.macro_strategist import run_macro_classification
        db = SessionLocal()
        try:
            run_macro_classification(db)
        except Exception as exc:
            logger.error("[macro_classification] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_macro_classification,
        CronTrigger(hour=7, minute=5, timezone=ET),
        id="macro_classification_daily",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=1800,
        coalesce=True,
        next_run_time=datetime.now(UTC),  # fire immediately on startup to confirm Discord wiring
    )
    logger.warning("[startup-trace] registered job macro_classification_daily (7:05 AM ET, fires immediately)")

    # ------------------------------------------------------------------
    # Proposal reaction handler: every 60s — polls Discord for CIO reactions
    # on #queen-proposals messages and routes to executors.
    # ------------------------------------------------------------------
    def _run_proposal_handler():
        from app.db.session import SessionLocal
        from agents.proposal_handler import run_proposal_handler
        db = SessionLocal()
        try:
            run_proposal_handler(db)
        except Exception as exc:
            logger.debug("[proposal_handler] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_proposal_handler,
        IntervalTrigger(seconds=60),
        id="proposal_reaction_handler",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job proposal_reaction_handler (every 60s)")

    # ------------------------------------------------------------------
    # Auto-defer check: every 5 minutes — proposals pending > 6h get deferred
    # CIO can still react ✅/❌ after deferral; handler logs it as 'late_decision'.
    # ------------------------------------------------------------------
    def _run_auto_defer_check():
        from app.db.session import SessionLocal
        from agents.proposal_handler import run_auto_defer_check
        db = SessionLocal()
        try:
            run_auto_defer_check(db)
        except Exception as exc:
            logger.debug("[proposal_auto_defer] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_auto_defer_check,
        IntervalTrigger(minutes=5),
        id="proposal_auto_defer",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job proposal_auto_defer (every 5 min, fires immediately)")

    # ------------------------------------------------------------------
    # Fleet heartbeat: every 30s — keeps /fund status dashboard live.
    # Publishes a lightweight "alive" tick to agent_heartbeats for each
    # deployed agent so /api/agents/status can report active/degraded/offline.
    # ------------------------------------------------------------------
    def _fleet_heartbeat():
        from app.db.session import SessionLocal
        from agents.bus import heartbeat
        db = SessionLocal()
        try:
            heartbeat(db, agent_id="queen")
            heartbeat(db, agent_id="researcher")
            heartbeat(db, agent_id="sentinel_devops")
            heartbeat(db, agent_id="risk_sentinel")
            heartbeat(db, agent_id="data_quality_watcher")
            heartbeat(db, agent_id="execution_auditor")
            heartbeat(db, agent_id="operations")
            heartbeat(db, agent_id="macro_strategist")
            heartbeat(db, agent_id="quant_researcher")
        except Exception as exc:
            logger.debug("[fleet_heartbeat] failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _fleet_heartbeat,
        IntervalTrigger(seconds=30),
        id="fleet_heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job fleet_heartbeat (every 30s, fires immediately)")

    # ------------------------------------------------------------------
    # Deploy 4.5.E — Defensive halt check: every 15 minutes
    # Tier A autonomous executor: pauses a bot on hard drawdown breach.
    # Max 3 auto-pauses/day; escalates to CRITICAL if cap is hit.
    # ------------------------------------------------------------------
    def _run_defensive_halt_check():
        from app.db.session import SessionLocal
        from agents.executors.auto_defensive_halt import run_defensive_halt_check
        db = SessionLocal()
        try:
            result = run_defensive_halt_check(db)
            logger.warning(
                "[defensive_halt_check] done — checked=%d halted=%d skipped_cap=%s",
                result.get("checked", 0),
                result.get("halted", 0),
                result.get("skipped_cap", False),
            )
        except Exception as exc:
            logger.error("[defensive_halt_check] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_defensive_halt_check,
        IntervalTrigger(minutes=15),
        id="defensive_halt_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(UTC),
    )
    logger.warning("[startup-trace] registered job defensive_halt_check (every 15 min, fires immediately)")

    # ------------------------------------------------------------------
    # Deploy 4.5.E — Resume check: every 2 minutes
    # Polls Discord for ▶️ reactions on auto-halt messages.
    # If CIO reacted, unpauses the bot and updates proposal_audit.
    # ------------------------------------------------------------------
    def _run_resume_check():
        from app.db.session import SessionLocal
        from agents.executors.auto_defensive_halt import run_resume_check
        db = SessionLocal()
        try:
            result = run_resume_check(db)
            if result.get("resumed", 0) > 0:
                logger.warning(
                    "[resume_check] resumed %d bot(s)", result["resumed"]
                )
        except Exception as exc:
            logger.error("[resume_check] job failed: %s", exc)
        finally:
            db.close()

    scheduler.add_job(
        _run_resume_check,
        IntervalTrigger(minutes=2),
        id="resume_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job resume_check (every 2 min)")

    # ------------------------------------------------------------------
    # Candidate Pipeline Daemon: 2:30 AM ET daily
    # Advances CANDIDATE→BACKTEST_DONE→WFA_DONE→SHADOW_PAPER→PROMOTED
    # ------------------------------------------------------------------
    def _run_pipeline_daemon():
        from app.db.session import SessionLocal
        from strategy_lab.core.pipeline.executor import advance_pipeline
        db = SessionLocal()
        try:
            result = advance_pipeline(db)
            logger.warning("[pipeline-daemon] run complete: %s", result)
        except Exception as exc:
            logger.error("[pipeline-daemon] failed: %s", exc, exc_info=True)
        finally:
            db.close()

    scheduler.add_job(
        _run_pipeline_daemon,
        CronTrigger(hour=2, minute=30, timezone=ET),
        id="candidate_pipeline_daemon",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=3600,
        coalesce=True,
    )
    logger.warning("[startup-trace] registered job candidate_pipeline_daemon (2:30 AM ET daily)")

    logger.warning(
        "[startup-trace] ALL BOT JOBS REGISTERED: stock_swing stock_day stock_lt "
        "crypto_swing crypto_day crypto_lt crypto_onchain "
        "crypto_quant_aggressive crypto_quant_scalper crypto_quant_mean_reversion "
        "options_income options_directional position_monitor dead_mans_switch "
        "quarantine_dupes_periodic daily_discord_digest strategy_scout_scan "
        "strategy_forge_scan signal_explain_pregen "
        "tsmom_multi_asset quality_factor value_quality crypto_meanrev_2163 earnings_nlp "
        "queen_morning queen_midday queen_close queen_evening "
        "queen_weekend_recap queen_weekly queen_regime_alert_check "
        "defensive_halt_check resume_check compute_bot_stats macro_classification_daily "
        "candidate_pipeline_daemon"
    )
