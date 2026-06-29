"""Shared idempotency gate for one-shot migrations.

Use at the top of any migration's run() function:

    from app.db.migrations._gate import already_ran, record
    _NAME = "mNNN_short_description_YYYY_MM"

    def run(conn):
        if already_ran(conn, _NAME):
            return {"skipped_reason": "already_applied", "executed": False}
        ...do work...
        record(conn, _NAME)
        return {"executed": True, ...}

Why: the 2026-06-28 capital regression (sum drifted from $1M to $2.6M on
deploy) was caused by m021 running on every boot — it had no gate and
re-overwrote m027's spec amounts to flat $200K. Same bomb can hide in any
ungated migration that UPDATEs canonical state.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def already_ran(conn, name: str) -> bool:
    try:
        return conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"),
            {"n": name},
        ).fetchone() is not None
    except Exception:
        return False


def record(conn, name: str) -> None:
    try:
        conn.execute(
            text(
                "INSERT INTO schema_migrations (migration_name) VALUES (:n)"
                " ON CONFLICT (migration_name) DO NOTHING"
            ),
            {"n": name},
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[gate] record(%s) failed: %s", name, exc)
