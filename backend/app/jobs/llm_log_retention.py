"""
LLM log retention cron — SHIP 3.

Prunes llm_call_log rows older than 90 days.
Runs daily at 03:00 ET via scheduler.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)

# Module-level import so tests can patch `app.jobs.llm_log_retention.SessionLocal`.
# If the DB session module is not yet available (e.g. during import in test env),
# we fall back to None and let the function handle the missing dependency.
try:
    from app.db.session import SessionLocal  # noqa: F401
except Exception:
    SessionLocal = None  # type: ignore[assignment,misc]


def prune_old_llm_logs() -> int:
    """
    DELETE FROM llm_call_log WHERE created_at < now-90 days.
    Returns deleted row count.

    Uses the module-level SessionLocal so the reference can be patched in tests.
    """
    import app.jobs.llm_log_retention as _self
    _SessionLocal = _self.SessionLocal

    if _SessionLocal is None:
        logger.error("[llm_log_retention] SessionLocal not available — skipping prune")
        return 0

    try:
        db = _SessionLocal()
        try:
            result = db.execute(
                text(
                    "DELETE FROM llm_call_log "
                    "WHERE created_at < datetime('now', '-90 days')"
                )
            )
            deleted = result.rowcount
            db.commit()
            logger.info("[llm_log_retention] Pruned %d rows older than 90 days", deleted)
            return deleted
        finally:
            db.close()
    except Exception as e:
        logger.error("[llm_log_retention] Prune failed: %s", e, exc_info=True)
        return 0
