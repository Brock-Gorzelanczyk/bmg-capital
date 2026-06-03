"""APScheduler integration for the six bot profiles.

setup_bot_scheduler(scheduler) is called from app/main.py lifespan,
after setup_monitoring_scheduler, using the same AsyncIOScheduler instance.
"""
from __future__ import annotations

import logging

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
    # crypto_swing: every 4 hours, 24/7
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_swing"),
        CronTrigger(hour="*/4", minute=0),
        id="bot_crypto_swing",
        replace_existing=True,
    )

    # ------------------------------------------------------------------
    # crypto_day: every 15 min, 24/7
    # ------------------------------------------------------------------
    scheduler.add_job(
        lambda: run_bot_profile("crypto_day"),
        CronTrigger(minute="*/15"),
        id="bot_crypto_day",
        replace_existing=True,
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

    logger.info(
        "strategy_lab: bot scheduler registered (stock_swing, stock_day, stock_lt, "
        "crypto_swing, crypto_day, crypto_lt, daily_briefing_email, dead_mans_switch)"
    )
