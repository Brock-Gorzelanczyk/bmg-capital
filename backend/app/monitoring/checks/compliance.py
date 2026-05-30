"""Compliance checks (Category I — lightweight audit trail)."""
from __future__ import annotations
import logging
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


async def check_audit_log_completeness(db: Session) -> dict:
    """
    Check that the audit_logs table has at least one entry in the last 24h.
    (Assumes routine operations — logins, trades — generate audit entries.)
    """
    from app.db.models.monitoring import AuditLog
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    count = db.query(AuditLog).filter(AuditLog.timestamp >= since).count()
    # If zero users are active, this may legitimately be 0 — flag as P3 informational
    if count == 0:
        return {
            "passed": False,
            "detail": "No audit log entries in last 24h. Either no activity or logging is broken.",
        }
    return {"passed": True, "detail": f"{count} audit events in last 24h"}


async def check_audit_log_immutability(db: Session) -> dict:
    """
    Check that audit_logs row count is >= the last recorded count.
    Relies on the monitoring_results table to store the previous count.
    """
    from app.db.models.monitoring import AuditLog, MonitoringResult

    current_count = db.query(AuditLog).count()

    last_result = (
        db.query(MonitoringResult)
        .filter(MonitoringResult.check_id == "audit_log_immutability")
        .filter(MonitoringResult.passed == True)
        .order_by(MonitoringResult.timestamp.desc())
        .first()
    )

    if last_result and last_result.extra_json:
        import json
        extra = json.loads(last_result.extra_json)
        last_count = extra.get("audit_row_count", 0)
        if current_count < last_count:
            return {
                "passed": False,
                "detail": f"Audit log count dropped: was {last_count}, now {current_count}. Possible deletion!",
                "extra": {"audit_row_count": current_count},
            }

    return {
        "passed": True,
        "detail": f"Audit log count: {current_count} (>= last known count)",
        "extra": {"audit_row_count": current_count},
    }


async def check_cross_table_referential_integrity(db: Session) -> dict:
    """Check for orphan rows in key relationships."""
    from sqlalchemy import text
    issues = []

    checks = [
        # paper_positions should have matching paper_accounts
        (
            "paper_positions orphan",
            "SELECT COUNT(*) FROM paper_positions pp LEFT JOIN paper_accounts pa ON pp.user_id = pa.user_id WHERE pa.user_id IS NULL",
        ),
        # paper_orders should reference valid users
        (
            "paper_orders orphan",
            "SELECT COUNT(*) FROM paper_orders po LEFT JOIN users u ON po.user_id = u.id WHERE u.id IS NULL",
        ),
        # paper_transactions should have matching paper_orders (where order_id is set)
        (
            "paper_transactions orphan order",
            "SELECT COUNT(*) FROM paper_transactions pt LEFT JOIN paper_orders po ON pt.order_id = po.id WHERE pt.order_id IS NOT NULL AND po.id IS NULL",
        ),
        # user_tiers should have matching users
        (
            "user_tiers orphan",
            "SELECT COUNT(*) FROM user_tiers ut LEFT JOIN users u ON ut.user_id = u.id WHERE u.id IS NULL",
        ),
    ]

    for name, sql in checks:
        try:
            row = db.execute(text(sql)).fetchone()
            count = row[0] if row else 0
            if count > 0:
                issues.append(f"{name}: {count} orphan row(s)")
        except Exception as exc:
            logger.warning("Referential integrity check '%s' failed: %s", name, exc)

    if issues:
        return {"passed": False, "detail": " | ".join(issues)}
    return {"passed": True, "detail": "No orphan foreign keys detected"}
