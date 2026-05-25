from __future__ import annotations

import logging
from datetime import datetime, timezone

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")

scheduler = AsyncIOScheduler(timezone=ET)

# ---------------------------------------------------------------------------
# In-memory monitor status — updated after each automation run
# ---------------------------------------------------------------------------

_monitor_status: dict = {
    "last_scan_at": None,    # ISO string (UTC)
    "stocks_scanned": 0,
    "signals_today": 0,
    "market_status": "closed",
}


def _current_market_status() -> str:
    """Return market phase based on current ET time."""
    now_et = datetime.now(ET)
    hour = now_et.hour
    minute = now_et.minute
    weekday = now_et.weekday()  # 0=Mon, 6=Sun

    if weekday >= 5:  # weekend
        return "closed"

    total_minutes = hour * 60 + minute

    # 4:00 AM – 9:30 AM ET
    if 4 * 60 <= total_minutes < 9 * 60 + 30:
        return "pre-market"
    # 9:30 AM – 4:00 PM ET
    if 9 * 60 + 30 <= total_minutes < 16 * 60:
        return "open"
    # 4:00 PM – 8:00 PM ET
    if 16 * 60 <= total_minutes < 20 * 60:
        return "after-hours"

    return "closed"


def get_monitor_status() -> dict:
    """Return a copy of the monitor status dict with a live market_status field."""
    return {
        **_monitor_status,
        "market_status": _current_market_status(),
    }


def _update_monitor_status(result: dict | None) -> None:
    """Update the in-memory monitor status after a scan run."""
    _monitor_status["last_scan_at"] = datetime.now(timezone.utc).isoformat()
    _monitor_status["market_status"] = _current_market_status()
    if result:
        _monitor_status["stocks_scanned"] = result.get("stocks_scanned", _monitor_status["stocks_scanned"])
        _monitor_status["signals_today"] = (
            _monitor_status.get("signals_today", 0)
            + result.get("entries", 0)
            + result.get("new_candidates", 0)
        )


# ---------------------------------------------------------------------------
# Job functions
# ---------------------------------------------------------------------------

async def run_intraday_signals() -> None:
    """Run intraday signal detection for watchlist symbols."""
    logger.info("Running intraday signal scan...")
    # TODO: wire up after DB session available


async def run_daily_recap_job() -> None:
    """Generate daily recaps for all active users at 4:15 PM ET, M-F."""
    logger.info("Starting scheduled daily recap generation...")
    try:
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.services.recap import generate_daily_recap

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            user_ids = [u.id for u in users]
        finally:
            db.close()

        if not user_ids:
            logger.info("No active users — skipping daily recap generation")
            return

        for user_id in user_ids:
            try:
                recap = await generate_daily_recap(user_id=user_id)
                logger.info(f"Daily recap generated for user {user_id}: {recap.recap_date}")
            except Exception as e:
                logger.error(f"Daily recap failed for user {user_id}: {e}", exc_info=True)
    except Exception as e:
        logger.error(f"Scheduled daily recap setup failed: {e}", exc_info=True)


async def run_daily_automation_job() -> None:
    """Run full strategy automation for all active users."""
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
            _update_monitor_status(None)
            return

        combined_result: dict = {
            "entries": 0,
            "new_candidates": 0,
            "stocks_scanned": 0,
        }
        for user_id in user_ids:
            try:
                result = await run_daily_automation(user_id=user_id)
                logger.info(f"Daily automation done for user {user_id}: {result}")
                combined_result["entries"] += result.get("entries", 0)
                combined_result["new_candidates"] += result.get("new_candidates", 0)
            except Exception as e:
                logger.error(f"Scheduled automation failed for user {user_id}: {e}", exc_info=True)

        _update_monitor_status(combined_result)

    except Exception as e:
        logger.error(f"Scheduled daily automation setup failed: {e}", exc_info=True)
        _update_monitor_status(None)


async def run_offhours_check() -> None:
    """
    Lightweight off-hours monitor: refresh last-known prices on open strategy
    trades and write a heartbeat log entry.
    """
    logger.info("Running off-hours monitor heartbeat...")
    try:
        from datetime import date
        from app.db.session import SessionLocal
        from app.db.models.users import User
        from app.db.models.strategy import StrategyTrade, DailyLog
        from app.screener.daily_runner import _get_prices_sync, _add_log

        db = SessionLocal()
        try:
            users = db.query(User).filter(User.is_active.is_(True)).all()
            today = date.today()

            for user in users:
                open_trades = db.query(StrategyTrade).filter(
                    StrategyTrade.status == "open",
                    StrategyTrade.user_id == user.id,
                ).all()

                if open_trades:
                    symbols = [t.symbol for t in open_trades]
                    prices = _get_prices_sync(symbols)
                    for trade in open_trades:
                        p = prices.get(trade.symbol)
                        if p and p > 0:
                            trade.last_known_price = p
                            db.add(trade)

                _add_log(
                    db,
                    today,
                    "monitor_heartbeat",
                    f"Off-hours check: {len(open_trades)} open position(s) monitored",
                    user_id=user.id,
                )

            db.commit()

        finally:
            db.close()

        _monitor_status["last_scan_at"] = datetime.now(timezone.utc).isoformat()
        _monitor_status["market_status"] = _current_market_status()
        logger.info("Off-hours heartbeat complete.")

    except Exception as e:
        logger.error(f"Off-hours check failed: {e}", exc_info=True)


# ---------------------------------------------------------------------------
# Scheduler setup
# ---------------------------------------------------------------------------

def setup_scheduler() -> None:
    """Register all scheduled jobs."""

    # --- Kept from original ---

    # After market close — main daily scan (new candidates + exits + equity snapshot)
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone=ET),
        id="daily_automation_close",
        replace_existing=True,
    )
    # Morning check — re-evaluate candidates using prior day's close data
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(day_of_week="mon-fri", hour=9, minute=35, timezone=ET),
        id="daily_automation_open",
        replace_existing=True,
    )

    # --- New: 24/7 monitoring jobs ---

    # market_scan: every 15 min, M-F, 9:30 AM – 4:00 PM ET
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/15",
            timezone=ET,
        ),
        id="market_scan",
        replace_existing=True,
    )

    # premarket_scan: every 30 min, M-F, 4:00 AM – 9:30 AM ET
    # CronTrigger handles "4-9" hours; the 9:30 boundary is close enough —
    # the 9:35 AM dedicated job picks up the open precisely.
    scheduler.add_job(
        run_daily_automation_job,
        CronTrigger(
            day_of_week="mon-fri",
            hour="4-8",
            minute="*/30",
            timezone=ET,
        ),
        id="premarket_scan",
        replace_existing=True,
    )

    # offhours_check: every 2 hours, every day (weekends included)
    scheduler.add_job(
        run_offhours_check,
        CronTrigger(minute=0, hour="*/2", timezone=ET),
        id="offhours_check",
        replace_existing=True,
    )

    # Daily recap: 4:15 PM ET, M-F — runs after automation closes out
    scheduler.add_job(
        run_daily_recap_job,
        CronTrigger(day_of_week="mon-fri", hour=16, minute=15, timezone=ET),
        id="daily_recap",
        replace_existing=True,
    )
