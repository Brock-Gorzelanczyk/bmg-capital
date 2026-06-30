"""m050 — create daily_audit_log table.

Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
Stores results of the daily Strategy Lab audit job (04:30 UTC cron).

Schema:
    id              INTEGER PRIMARY KEY AUTOINCREMENT
    run_at          TEXT NOT NULL  (ISO8601 UTC, '2026-06-30T04:30:00Z')
    overall_status  TEXT NOT NULL  ('GREEN' | 'YELLOW' | 'RED')
    checks_json     TEXT NOT NULL  (JSON list of {name, status, details})
    alerts_json     TEXT NOT NULL  (JSON list of strings, [] if none)
    summary_markdown TEXT NOT NULL (Discord-formatted summary)

DO NOT add UNIQUE on run_at — manual run-now + cron can both write rows.
DO NOT add user_id — global ops state, not per-user.
TEXT (not JSON type) for SQLite portability (matches m023, m044 pattern).
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def upgrade(db) -> None:
    """Create daily_audit_log table and index. Idempotent."""
    db.execute(text("""
        CREATE TABLE IF NOT EXISTS daily_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_at TEXT NOT NULL,
            overall_status TEXT NOT NULL,
            checks_json TEXT NOT NULL,
            alerts_json TEXT NOT NULL,
            summary_markdown TEXT NOT NULL
        )
    """))
    db.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_daily_audit_log_run_at
            ON daily_audit_log(run_at DESC)
    """))
    db.commit()
    logger.warning("[m050] daily_audit_log upgrade complete")
