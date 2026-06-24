"""m016 — Add `health_status` column to bot_health.

The fleet_sentinel.red_transition check and queen.py briefing both reference
`bot_health.health_status`, but the column was never created. Production
sqlite logs show:

    [fleet_sentinel] red_transition check failed:
    (sqlite3.OperationalError) no such column: bh.health_status

This migration adds the column as nullable VARCHAR(16) so existing rows
remain valid. Expected values: 'GREEN' | 'YELLOW' | 'RED' | NULL.

Idempotent — skips if the column already exists.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return any(r[1] == column for r in rows)


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return bool(rows)


def run(conn) -> dict:
    added: list[str] = []

    if not _table_exists(conn, "bot_health"):
        logger.info("[m016] bot_health table missing — no-op")
        return {"added": added, "skipped_reason": "bot_health table missing"}

    if _column_exists(conn, "bot_health", "health_status"):
        logger.info("[m016] bot_health.health_status already exists — no-op")
        return {"added": added}

    # sqlite ALTER TABLE ADD COLUMN does not support IF NOT EXISTS,
    # but we already checked above. Nullable so existing rows survive.
    conn.execute(text(
        "ALTER TABLE bot_health ADD COLUMN health_status VARCHAR(16)"
    ))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_bot_health_status "
        "ON bot_health (date, health_status)"
    ))
    conn.commit()
    added.append("bot_health.health_status")
    logger.info("[m016] added bot_health.health_status (nullable VARCHAR(16))")
    return {"added": added}
