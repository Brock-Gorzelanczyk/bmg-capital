from __future__ import annotations

import logging

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

scheduler = AsyncIOScheduler(timezone=ET)


async def run_intraday_signals() -> None:
    """Run intraday signal detection for watchlist symbols."""
    logger.info("Running intraday signal scan...")
    # TODO: wire up after DB session available


async def run_daily_automation_job() -> None:
    """Run full strategy automation for all active users after market close."""
    logger.info("Starting scheduled daily automation...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.screener.daily_runner import run_daily_automation

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            user_ids = [u.id for u in users]
        finally:
            db.close()

        if not user_ids:
            logger.info("No active users — skipping scheduled automation")
            return

        for user_id in user_ids:
            try:
                result = await run_daily_automation(user_id=user_id)
                logger.info(f"Daily automation done for user {user_id}: {result}")
            except Exception as e:
                logger.error(f"Scheduled automation failed for user {user_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Scheduled daily automation setup failed: {e}", exc_info=True)


def setup_scheduler() -> None:
    """Register all scheduled jobs."""
    scheduler.add_job(
        run_intraday_signals,
        CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=ET),
        id="intraday_signals",
        replace_existing=True,
    )
    # After market close — main daily scan (new candidates + exits + equity snapshot)
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=ET),
        id="daily_automation_close",
        replace_existing=True,
    )
    # Morning check — re-evaluate candidates using prior day's close data
    # catches any triggers that fired on yesterday's bars
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=35, timezone=ET),
        id="daily_automation_open",
        replace_existing=True,
    )
