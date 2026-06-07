"""APScheduler integration for the six bot profiles.

setup_bot_scheduler(scheduler) is called from app/main.py lifespan,
after setup_monitoring_scheduler, using the same AsyncIOScheduler instance.
"""
from __future__ import annotations

import logging
from datetime import datetime

import pytz
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")
UTC = pytz.utc


def setup_bot_scheduler(scheduler) -> None:
    """Register the six bot-profile cron jobs.

    Schedule reference (all times ET unless noted):
      stock_swing  — weekdays 4:05 PM ET (market close + 5 min)
      stock_lt     — first Tuesday of each month, 10:00 AM ET
      crypto_swing — every 4 hours (24/7)
      crypto_lt    — Monday 10:00 AM UTC (weekly DCA)
    """
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
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=ET),
        id="bot_stock_day",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # stock_lt: first Tuesday of each month, 10:00 AM ET
    # APScheduler: day='1-7' means "any day 1-7", day_of_week='tue' → first Tue
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("stock_lt"),
        CronTrigger(day_of_week="tue", day="1-7", hour=10, minute=0, timezone=ET),
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
    )

    # ------------------------------------------------------------------
    # crypto_day: every 1 min, 24/7 — crypto has no market-hours gate
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_day"),
        CronTrigger(minute="*/1"),
        id="bot_crypto_day",
        replace_existing=True,
        next_run_time=datetime.now(UTC),  # fire immediately on startup
    )

    # ------------------------------------------------------------------
    # crypto_lt DCA: Monday 10:00 AM UTC
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_lt"),
        CronTrigger(day_of_week="mon", hour=10, minute=0, timezone=UTC),
        id="bot_crypto_lt_dca",
        replace_existing=True,
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
    # Position monitor: every 1 minute, 24/7
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
        CronTrigger(minute="*/1"),
        id="position_monitor",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
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
    # crypto_quant_aggressive: every 5 min, 24/7
    # High-turnover quant bot — 20-coin universe, 5-signal stack.
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_quant_aggressive"),
        CronTrigger(minute="*/5"),
        id="bot_crypto_quant_aggressive",
        replace_existing=True,
        next_run_time=datetime.now(UTC),
    )

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
            from app.db.models.bots import BotSignal, BotDailyPnL
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
                post_monthly_recap({
                    "month_name": first_prev.strftime("%B %Y"),
                    "signals":    signals,
                    "trades":     0,  # TODO: wire bot_trades table
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

    logger.info(
        "strategy_lab: bot scheduler registered (stock_swing, stock_day, stock_lt, "
        "crypto_swing, crypto_day, crypto_lt, crypto_onchain, crypto_quant_aggressive, "
        "discord_digest, discord_leaderboard, daily_briefing_email, dead_mans_switch)"
    )
