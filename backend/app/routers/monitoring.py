"""
Monitoring router.

GET  /api/monitoring/health          — public, live health check
GET  /api/monitoring/history         — last 48 health snapshots (legacy, in-memory)
GET  /api/monitoring/integrity       — on-demand financial integrity
POST /api/monitoring/sentinel        — trigger AI sentinel
GET  /api/monitoring/sentinel/latest — last sentinel result
GET  /api/monitoring/checks          — full check registry (id, category, frequency, severity, runbook)
GET  /api/monitoring/results         — recent check results from DB (query param: check_id, category, hours=24)
GET  /api/monitoring/status          — category-level green/yellow/red rollup
"""
from __future__ import annotations

import logging
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.dependencies import get_db, get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

_ADMIN_EMAILS = {"32bgorzelanczyk@gmail.com", "demo@bmgcapital.com"}


def _admin_required(current_user=Depends(get_current_user)):
    if not getattr(current_user, "is_admin", False) and current_user.email not in _ADMIN_EMAILS:
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

# Legacy in-memory ring buffer (kept for /history backward compat)
_health_history: deque[dict] = deque(maxlen=48)
_latest_integrity: dict | None = None
_latest_sentinel: dict | None = None


# ── Scheduler setup ───────────────────────────────────────────────────────────

def setup_monitoring_scheduler(scheduler) -> None:
    """Register all check frequency buckets + cleanup job."""
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger

    # Per-frequency runners
    scheduler.add_job(
        _run_minute_checks, IntervalTrigger(seconds=60),
        id="monitoring_minute", replace_existing=True,
    )
    scheduler.add_job(
        _run_5min_checks, IntervalTrigger(minutes=5),
        id="monitoring_5min", replace_existing=True,
    )
    scheduler.add_job(
        _run_15min_checks, IntervalTrigger(minutes=15),
        id="monitoring_15min", replace_existing=True,
    )
    scheduler.add_job(
        _run_hourly_checks, IntervalTrigger(hours=1),
        id="monitoring_hourly", replace_existing=True,
    )
    scheduler.add_job(
        _run_daily_checks, CronTrigger(hour=6, minute=0, timezone="UTC"),
        id="monitoring_daily", replace_existing=True,
    )

    # Legacy health check → still feeds _health_history for /history endpoint
    scheduler.add_job(
        _legacy_health_check, IntervalTrigger(seconds=60),
        id="monitoring_health_legacy", replace_existing=True,
    )

    # 90-day cleanup at midnight
    scheduler.add_job(
        _run_cleanup, CronTrigger(hour=0, minute=30, timezone="UTC"),
        id="monitoring_cleanup", replace_existing=True,
    )

    logger.info("Monitoring scheduler jobs registered (registry-driven).")


async def _run_minute_checks():
    try:
        from app.monitoring.engine import run_checks_by_frequency
        from app.db.session import SessionLocal
        await run_checks_by_frequency("minute", db_factory=SessionLocal)
    except Exception as exc:
        logger.error("Minute checks failed: %s", exc)


async def _run_5min_checks():
    try:
        from app.monitoring.engine import run_checks_by_frequency
        from app.db.session import SessionLocal
        await run_checks_by_frequency("5min", db_factory=SessionLocal)
    except Exception as exc:
        logger.error("5min checks failed: %s", exc)


async def _run_15min_checks():
    try:
        from app.monitoring.engine import run_checks_by_frequency
        from app.db.session import SessionLocal
        await run_checks_by_frequency("15min", db_factory=SessionLocal)
    except Exception as exc:
        logger.error("15min checks failed: %s", exc)


async def _run_hourly_checks():
    try:
        from app.monitoring.engine import run_checks_by_frequency
        from app.db.session import SessionLocal
        await run_checks_by_frequency("hourly", db_factory=SessionLocal)
    except Exception as exc:
        logger.error("Hourly checks failed: %s", exc)


async def _run_daily_checks():
    try:
        from app.monitoring.engine import run_checks_by_frequency
        from app.db.session import SessionLocal
        await run_checks_by_frequency("daily", db_factory=SessionLocal)
        # Also run legacy sentinel
        await _scheduled_ai_sentinel()
    except Exception as exc:
        logger.error("Daily checks failed: %s", exc)


async def _run_cleanup():
    try:
        from app.monitoring.engine import cleanup_old_results
        from app.db.session import SessionLocal
        await cleanup_old_results(db_factory=SessionLocal)
    except Exception as exc:
        logger.error("Monitoring cleanup failed: %s", exc)


async def _legacy_health_check():
    try:
        from app.services.monitoring import check_health
        result = await check_health()
        _health_history.append(result)
    except Exception as exc:
        logger.error("Legacy health check failed: %s", exc)
        _health_history.append({
            "db": "error", "api": "error", "latency_ms": 0,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        })


async def _scheduled_ai_sentinel():
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
        logger.error("AI sentinel scheduled run failed: %s", exc)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/health")
async def get_health():
    try:
        from app.services.monitoring import check_health
        return await check_health()
    except Exception as exc:
        return {"db": "error", "api": "error", "latency_ms": 0,
                "timestamp": datetime.now(timezone.utc).isoformat(), "error": str(exc)}


@router.get("/history")
async def get_history(_user=Depends(_admin_required)):
    return {"history": list(_health_history)}


@router.get("/integrity")
async def get_integrity(db: Session = Depends(get_db), _user=Depends(_admin_required)):
    global _latest_integrity
    try:
        from app.services.monitoring import check_financial_integrity
        result = await check_financial_integrity(db)
        _latest_integrity = result
        return result
    except Exception as exc:
        return {"passed": False, "checks": [{"name": "runner", "passed": False, "detail": str(exc)}],
                "timestamp": datetime.now(timezone.utc).isoformat()}


@router.post("/sentinel")
async def trigger_sentinel(db: Session = Depends(get_db), _user=Depends(_admin_required)):
    global _latest_sentinel
    try:
        from app.services.monitoring import run_ai_sentinel
        from app.config import settings
        result = await run_ai_sentinel(db, settings.anthropic_api_key)
        _latest_sentinel = result
        return result
    except Exception as exc:
        return {"findings": [{"priority": "P2", "title": "Sentinel trigger failed",
                              "description": str(exc), "action": "Check server logs."}],
                "generated_at": datetime.now(timezone.utc).isoformat()}


@router.get("/sentinel/latest")
async def get_sentinel_latest(_user=Depends(_admin_required)):
    if _latest_sentinel is None:
        return {"findings": [], "generated_at": None,
                "message": "No sentinel run yet. POST /api/monitoring/sentinel to trigger."}
    return _latest_sentinel


@router.get("/checks")
async def list_checks(_user=Depends(_admin_required)):
    """Return the full check registry — id, category, frequency, severity, runbook."""
    from app.monitoring.registry import get_registry
    registry = get_registry()
    return {
        "checks": [
            {
                "id": c.id,
                "category": c.category,
                "frequency": c.frequency,
                "severity_on_fail": c.severity_on_fail,
                "runbook": c.runbook,
                "expected_pass_rate": c.expected_pass_rate,
                "market_hours_only": c.market_hours_only,
                "enabled": c.enabled,
            }
            for c in registry
        ],
        "total": len(registry),
    }


@router.get("/results")
async def get_results(
    check_id: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    hours: int = Query(24, ge=1, le=24 * 90),
    passed: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _user=Depends(_admin_required),
):
    """Recent check results from DB. Filter by check_id, category, hours, passed."""
    from app.db.models.monitoring import MonitoringResult
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    q = db.query(MonitoringResult).filter(MonitoringResult.timestamp >= since)
    if check_id:
        q = q.filter(MonitoringResult.check_id == check_id)
    if category:
        q = q.filter(MonitoringResult.category == category)
    if passed is not None:
        q = q.filter(MonitoringResult.passed == passed)
    rows = q.order_by(MonitoringResult.timestamp.desc()).limit(500).all()
    return {
        "results": [
            {
                "id": r.id,
                "check_id": r.check_id,
                "category": r.category,
                "passed": r.passed,
                "severity": r.severity,
                "detail": r.detail,
                "runbook": r.runbook,
                "duration_ms": r.duration_ms,
                "timestamp": r.timestamp.isoformat(),
            }
            for r in rows
        ],
        "count": len(rows),
        "since": since.isoformat(),
    }


@router.get("/status")
async def get_status(
    db: Session = Depends(get_db),
    _user=Depends(_admin_required),
):
    """
    Category-level green/yellow/red rollup.
    Green: all checks passed in last window.
    Yellow: some checks failed (P3 only).
    Red: any P1/P2 check failed.
    """
    from app.db.models.monitoring import MonitoringResult
    from app.monitoring.registry import get_registry

    since = datetime.now(timezone.utc) - timedelta(hours=2)
    registry = get_registry()
    categories = list({c.category for c in registry})

    status_map = {}
    for cat in categories:
        recent = (
            db.query(MonitoringResult)
            .filter(
                MonitoringResult.category == cat,
                MonitoringResult.timestamp >= since,
            )
            .order_by(MonitoringResult.timestamp.desc())
            .all()
        )
        # Get latest result per check_id
        seen = {}
        for r in recent:
            if r.check_id not in seen:
                seen[r.check_id] = r

        failures = [r for r in seen.values() if not r.passed]
        p1_p2_failures = [r for r in failures if r.severity in ("P1", "P2")]
        p3_failures = [r for r in failures if r.severity == "P3"]

        if p1_p2_failures:
            color = "red"
        elif p3_failures:
            color = "yellow"
        elif not seen:
            color = "gray"  # no data yet
        else:
            color = "green"

        status_map[cat] = {
            "status": color,
            "total_checks": len([c for c in registry if c.category == cat]),
            "checks_with_data": len(seen),
            "failures_p1_p2": len(p1_p2_failures),
            "failures_p3": len(p3_failures),
            "last_run": max(
                (r.timestamp.isoformat() for r in seen.values()), default=None
            ),
        }

    return {"categories": status_map, "as_of": datetime.now(timezone.utc).isoformat()}
