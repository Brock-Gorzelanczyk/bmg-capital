"""
Monitoring router — health checks, financial integrity, AI sentinel.

All endpoints are wrapped in try/except so monitoring never crashes the app.
Endpoints:
  GET  /api/monitoring/health          — public, no auth
  GET  /api/monitoring/integrity       — requires auth
  GET  /api/monitoring/history         — requires auth
  POST /api/monitoring/sentinel        — requires auth, triggers AI sentinel
  GET  /api/monitoring/sentinel/latest — requires auth, returns last sentinel result
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

# ---------------------------------------------------------------------------
# In-memory ring buffers — no DB needed
# ---------------------------------------------------------------------------

_health_history: deque[dict] = deque(maxlen=48)
_latest_integrity: dict | None = None
_latest_sentinel: dict | None = None


# ---------------------------------------------------------------------------
# Scheduler setup — called once from main.py lifespan
# ---------------------------------------------------------------------------

def setup_monitoring_scheduler(scheduler) -> None:
    """Register health-check and integrity/sentinel jobs on the existing scheduler."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    # Health check every 60 seconds
    scheduler.add_job(
        _scheduled_health_check,
        IntervalTrigger(seconds=60),
        id="monitoring_health_check",
        replace_existing=True,
    )

    # Financial integrity daily at 17:00 UTC
    scheduler.add_job(
        _scheduled_integrity_check,
        CronTrigger(hour=17, minute=0, timezone="UTC"),
        id="monitoring_integrity_daily",
        replace_existing=True,
    )

    # AI sentinel daily at 06:00 UTC
    scheduler.add_job(
        _scheduled_ai_sentinel,
        CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="monitoring_ai_sentinel_daily",
        replace_existing=True,
    )

    logger.info("Monitoring scheduler jobs registered.")


# ---------------------------------------------------------------------------
# Scheduled job functions
# ---------------------------------------------------------------------------

async def _scheduled_health_check() -> None:
    """Run health check and append to ring buffer."""
    try:
        from app.services.monitoring import check_health
        result = await check_health()
        _health_history.append(result)
    except Exception as exc:
        logger.error("Scheduled health check failed: %s", exc, exc_info=True)
        _health_history.append({
            "db": "error",
            "api": "error",
            "latency_ms": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        })


async def _scheduled_integrity_check() -> None:
    """Run financial integrity check; send webhook alert if any check fails."""
    global _latest_integrity
    try:
        from app.services.monitoring import check_financial_integrity, send_webhook_alert
        from app.config import settings
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            result = await check_financial_integrity(db)
        finally:
            db.close()

        _latest_integrity = result

        if not result["passed"] and settings.alert_webhook_url:
            failed = [c for c in result["checks"] if not c["passed"]]
            detail = "\n".join(f"• {c['name']}: {c['detail']}" for c in failed)
            await send_webhook_alert(
                settings.alert_webhook_url,
                "Financial Integrity Check Failed",
                detail,
                "P1",
            )
    except Exception as exc:
        logger.error("Scheduled integrity check failed: %s", exc, exc_info=True)


async def _scheduled_ai_sentinel() -> None:
    """Run AI sentinel; store result in memory."""
    global _latest_sentinel
    try:
        from app.services.monitoring import run_ai_sentinel
        from app.config import settings
        from app.db.session import SessionLocal

        db = SessionLocal()
        try:
            result = await run_ai_sentinel(db, settings.anthropic_api_key)
        finally:
            db.close()

        _latest_sentinel = result
    except Exception as exc:
        logger.error("Scheduled AI sentinel failed: %s", exc, exc_info=True)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/health")
async def get_health():
    """Current system health — no auth required."""
    try:
        from app.services.monitoring import check_health
        return await check_health()
    except Exception as exc:
        logger.error("Health endpoint error: %s", exc)
        return {
            "db": "error",
            "api": "error",
            "latency_ms": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }


@router.get("/history")
async def get_history(_user=Depends(get_current_user)):
    """Last 48 health snapshots from in-memory ring buffer."""
    return {"history": list(_health_history)}


@router.get("/integrity")
async def get_integrity(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Run financial integrity check on demand and return results."""
    global _latest_integrity
    try:
        from app.services.monitoring import check_financial_integrity
        result = await check_financial_integrity(db)
        _latest_integrity = result
        return result
    except Exception as exc:
        logger.error("Integrity endpoint error: %s", exc)
        return {
            "passed": False,
            "checks": [{"name": "runner", "passed": False, "detail": str(exc)}],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@router.post("/sentinel")
async def trigger_sentinel(
    db: Session = Depends(get_db),
    _user=Depends(get_current_user),
):
    """Manually trigger AI sentinel analysis."""
    global _latest_sentinel
    try:
        from app.services.monitoring import run_ai_sentinel
        from app.config import settings
        result = await run_ai_sentinel(db, settings.anthropic_api_key)
        _latest_sentinel = result
        return result
    except Exception as exc:
        logger.error("Sentinel trigger endpoint error: %s", exc)
        return {
            "findings": [{
                "priority": "P2",
                "title": "Sentinel trigger failed",
                "description": str(exc),
                "action": "Check server logs.",
            }],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }


@router.get("/sentinel/latest")
async def get_sentinel_latest(_user=Depends(get_current_user)):
    """Return latest AI sentinel result (stored in memory)."""
    if _latest_sentinel is None:
        return {
            "findings": [],
            "generated_at": None,
            "message": "No sentinel run yet. Use POST /api/monitoring/sentinel to trigger one.",
        }
    return _latest_sentinel
