"""m098 — Add breach_on_adopt flag + remediation_ticket_id to bot_positions.

Per PM Claude 2026-08-07 P0-1 correction: risk gates were guarding one
entry point of four. Every adopter path (orphan, catchall, rebuild)
bypassed `_check_leg_notional_gate`. Fix per directive:

- Adopts that violate caps are ACCEPTED (position exists at broker;
  refusing to record it recreates the orphan class), but flagged
  `breach_on_adopt=true` and auto-ticketed for remediation.
- I14 invariant will assert: `breach_on_adopt=true AND
  remediation_ticket_id IS NULL` = zero rows in violation.

Nullable columns; safe additive DDL.
"""
from __future__ import annotations

import logging
from sqlalchemy import text
from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)
_MIGRATION_NAME = "m098_breach_on_adopt_2026_08_07"


def _add(conn, col_sql: str, col_name: str) -> None:
    try:
        conn.execute(text(f"ALTER TABLE bot_positions ADD COLUMN IF NOT EXISTS {col_sql}"))
    except Exception:
        try:
            conn.execute(text(f"SELECT {col_name} FROM bot_positions LIMIT 1")).fetchone()
        except Exception:
            conn.execute(text(f"ALTER TABLE bot_positions ADD COLUMN {col_sql}"))


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    _add(conn, "breach_on_adopt BOOLEAN DEFAULT 0", "breach_on_adopt")
    _add(conn, "breach_reason VARCHAR(200)", "breach_reason")
    _add(conn, "remediation_ticket_id VARCHAR(64)", "remediation_ticket_id")

    if hasattr(conn, "commit"):
        conn.commit()

    logger.warning("[m098] added bot_positions.breach_on_adopt + breach_reason + remediation_ticket_id")
    record(conn, _MIGRATION_NAME)
    return {"executed": True}
