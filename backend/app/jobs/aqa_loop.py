"""AQA scheduled loop: run_aqa_cycle every 30 min (default).

Skips if AQA_ENABLED != 'true'. Never raises. Wraps cycle in Sentry transaction.
Uses existing AsyncIOScheduler from app; NOT a new BackgroundScheduler.

Wire-up: call register_aqa_jobs(scheduler) from main.py after
setup_monitoring_scheduler() and before scheduler.start().

# TODO PHASE B: add manual POST /api/admin/aqa/run-cycle trigger
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_aqa_scheduled() -> None:
    """APScheduler callback. Wraps run_aqa_cycle in Sentry transaction.
    Skips if AQA_ENABLED != 'true'. Never raises.
    """
    import os

    if os.getenv("AQA_ENABLED", "false").strip().lower() != "true":
        logger.debug("[aqa-loop] skipped: AQA_ENABLED != true")
        return

    try:
        import sentry_sdk
    except ImportError:
        sentry_sdk = None  # type: ignore[assignment]

    from app.db.session import SessionLocal
    from app.agents.aqa import run_aqa_cycle

    db = SessionLocal()
    try:
        if sentry_sdk:
            with sentry_sdk.start_transaction(op="aqa_cycle", name="aqa_cycle"):
                outcome = run_aqa_cycle(db)
        else:
            outcome = run_aqa_cycle(db)
        logger.info("[aqa-loop] cycle outcome: %s", outcome)
    except Exception as exc:
        logger.error("[aqa-loop] cycle raised: %s", exc, exc_info=True)
    finally:
        db.close()


def register_aqa_jobs(scheduler) -> None:
    """Add the AQA job to the given AsyncIOScheduler.

    Called from main.py after setup_bot_scheduler() and before scheduler.start().
    AQA_LOOP_INTERVAL_MINUTES defaults to 30. Non-numeric value raises at registration
    (config error should fail loud at boot, not silent at every cycle).
    """
    import os
    from apscheduler.triggers.interval import IntervalTrigger

    interval_min = int(os.getenv("AQA_LOOP_INTERVAL_MINUTES", "30"))
    scheduler.add_job(
        run_aqa_scheduled,
        IntervalTrigger(minutes=interval_min),
        id="aqa_loop",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    logger.warning(
        "[aqa-loop] registered aqa_loop job (interval=%d min, AQA_ENABLED=%s)",
        interval_min,
        os.getenv("AQA_ENABLED", "false"),
    )
