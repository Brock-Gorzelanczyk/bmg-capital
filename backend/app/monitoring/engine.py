"""
Monitoring engine — runs checks from registry, stores results, handles alert delivery.

Key behaviors:
- Every check is independent — failure/exception in one never affects others
- Alert deduplication: same check + severity won't re-alert within 1 hour
- Quiet hours: P2/P3 alerts suppressed 22:00–07:00 UTC; P1 always fires
- Results stored in monitoring_results table for 90-day trending
- Cleanup job removes results older than 90 days
"""
from __future__ import annotations
import asyncio
import json
import logging
import math
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.monitoring.registry import CheckConfig, get_registry
from app.db.models.monitoring import MonitoringResult

logger = logging.getLogger(__name__)

# ── Alert deduplication ───────────────────────────────────────────────────────
_last_alerted: dict[str, datetime] = {}  # check_id → last_alerted_at
DEDUP_WINDOW = timedelta(hours=1)
QUIET_HOURS_START = 22  # 10 PM UTC
QUIET_HOURS_END = 7     # 7 AM UTC


def _in_quiet_hours() -> bool:
    hour = datetime.now(timezone.utc).hour
    if QUIET_HOURS_START > QUIET_HOURS_END:
        return hour >= QUIET_HOURS_START or hour < QUIET_HOURS_END
    return QUIET_HOURS_START <= hour < QUIET_HOURS_END


def _should_alert(check_id: str, severity: str) -> bool:
    """P1 always alerts. P2/P3 respect quiet hours + dedup."""
    if severity == "P1":
        # P1: only dedup (1h), never quiet hours
        last = _last_alerted.get(check_id)
        return last is None or (datetime.now(timezone.utc) - last) > DEDUP_WINDOW
    # P2/P3: dedup + quiet hours
    if _in_quiet_hours():
        return False
    last = _last_alerted.get(check_id)
    return last is None or (datetime.now(timezone.utc) - last) > DEDUP_WINDOW


def _record_alert(check_id: str) -> None:
    _last_alerted[check_id] = datetime.now(timezone.utc)


# ── Single check runner ────────────────────────────────────────────────────────

async def run_check(config: CheckConfig, db: Session | None = None) -> dict[str, Any]:
    """
    Run one check. Returns result dict. Never raises.

    Result shape:
    {
        check_id: str,
        category: str,
        passed: bool,
        severity: str,
        detail: str,
        runbook: str,
        duration_ms: int,
        timestamp: str,
    }
    """
    t0 = time.monotonic()
    passed = False
    detail = ""
    extra: dict | None = None

    try:
        if config.needs_db and db is not None:
            raw = await config.fn(db)
        elif config.needs_db:
            # Shouldn't happen but fail gracefully
            detail = "Check requires DB but no session was provided."
            raw = {"passed": False, "detail": detail}
        else:
            raw = await config.fn()

        if isinstance(raw, dict):
            passed = bool(raw.get("passed", False))
            detail = raw.get("detail", "")
            extra = raw.get("extra")
        elif isinstance(raw, bool):
            passed = raw
        else:
            passed = bool(raw)

    except Exception as exc:
        logger.error("Check %s raised: %s", config.id, exc, exc_info=True)
        passed = False
        detail = f"Check function raised: {type(exc).__name__}: {exc}"

    duration_ms = int((time.monotonic() - t0) * 1000)

    result = {
        "check_id": config.id,
        "category": config.category,
        "passed": passed,
        "severity": config.severity_on_fail if not passed else "ok",
        "detail": detail or ("OK" if passed else "Failed — no detail provided"),
        "runbook": config.runbook if not passed else "",
        "duration_ms": duration_ms,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "extra": extra,
    }

    return result


# ── Batch runner (by frequency) ───────────────────────────────────────────────

async def run_checks_by_frequency(frequency: str, db_factory=None) -> list[dict]:
    """Run all checks matching `frequency`. Store results. Fire alerts."""
    registry = get_registry()
    configs = [c for c in registry if c.frequency == frequency and c.enabled]

    if not configs:
        return []

    results = []
    for config in configs:
        db = db_factory() if (config.needs_db and db_factory) else None
        try:
            result = await run_check(config, db=db)
            results.append(result)
            # Persist
            if db_factory:
                persist_db = db_factory()
                try:
                    await _persist_result(result, persist_db)
                finally:
                    persist_db.close()
            # Alert
            if not result["passed"]:
                await _maybe_alert(config, result)
        except Exception as exc:
            logger.error("Batch runner error for %s: %s", config.id, exc)
        finally:
            if db is not None:
                db.close()

    return results


async def _persist_result(result: dict, db: Session) -> None:
    try:
        row = MonitoringResult(
            check_id=result["check_id"],
            category=result["category"],
            passed=result["passed"],
            severity=result["severity"],
            detail=result["detail"][:2000],
            runbook=result["runbook"][:1000],
            extra_json=json.dumps(result.get("extra")) if result.get("extra") else None,
            duration_ms=result["duration_ms"],
            timestamp=datetime.now(timezone.utc),
        )
        db.add(row)
        db.commit()
    except Exception as exc:
        logger.error("Failed to persist monitoring result: %s", exc)
        db.rollback()


async def _maybe_alert(config: CheckConfig, result: dict) -> None:
    severity = config.severity_on_fail
    if not _should_alert(config.id, severity):
        return
    _record_alert(config.id)
    try:
        from app.services.monitoring import send_webhook_alert
        from app.config import settings
        if settings.alert_webhook_url:
            await send_webhook_alert(
                settings.alert_webhook_url,
                f"[{severity}] {config.id} failed",
                f"{result['detail']}\n\n{config.runbook}",
                severity,
            )
    except Exception as exc:
        logger.warning("Alert delivery failed: %s", exc)


# ── Cleanup job (called daily) ────────────────────────────────────────────────

async def cleanup_old_results(db_factory) -> None:
    """Delete monitoring_results rows older than 90 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    db = db_factory()
    try:
        deleted = db.query(MonitoringResult).filter(
            MonitoringResult.timestamp < cutoff
        ).delete()
        db.commit()
        logger.info("Monitoring cleanup: deleted %d rows older than 90 days", deleted)
    except Exception as exc:
        logger.error("Cleanup failed: %s", exc)
        db.rollback()
    finally:
        db.close()
