"""m097 — Unique partial index on active bot_positions.

Prevents the class of bug that hit today (2026-08-07): a mid-write
container restart during PITR-enable caused ~30 duplicate BotPosition
inserts on same (allocation_id, symbol, side) — long+short pairs on
the same underlying, phantom qty values, none of which existed at
Alpaca.

This index makes those duplicate inserts fail cleanly at the DB layer
instead of silently succeeding. Recurrence auto-blocks with a
UNIQUE constraint error the runner can catch and log.

SQLite 3.8+ supports partial indexes via WHERE clause. No PG compat
worry — production is SQLite on /data volume (per m096 note + admin
db-driver diagnostic 2026-08-07).

Prerequisite state (verified 2026-08-07 17:20 UTC before applying):
- 86 open non-quarantined rows, 0 (allocation_id, symbol, side)
  duplicates in-bot; 5 cross-allocation same-key pairs (catchall vs
  options bot on same OCC, legitimately distinct owners).

Prevention entry for issue #3 (duplicate bot_allocations) recurrence
class and the 2026-08-07 restart-drift incident.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m097_bot_positions_active_uniq_2026_08_07"


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    # Idempotent CREATE INDEX IF NOT EXISTS
    conn.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_bot_positions_active "
        "ON bot_positions(allocation_id, symbol, side) "
        "WHERE closed_at IS NULL AND quarantined_at IS NULL"
    ))
    if hasattr(conn, "commit"):
        conn.commit()

    logger.warning("[m097] created uq_bot_positions_active partial index")
    record(conn, _MIGRATION_NAME)
    return {"executed": True}
