"""m095 — Add composite_score_at_execution to bot_trades.

Time-boxed threshold experiment (follow-up to 985f176d): tag every trade
with the composite discipline score at the moment of execution so that
after 14 days we can compare the 30-59 band (previously blocked by the
default 60 gate) against the 60+ band (would have been admitted before).

Auto-revert candidate lives in app/services/threshold_experiment.py —
this migration just adds the column. Nullable INT so historical trades
(pre-experiment) return NULL and don't pollute the comparison.

Idempotent via IF NOT EXISTS + _gate.record().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m095_add_composite_score_at_execution_2026_07_13"


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    # Postgres: ADD COLUMN IF NOT EXISTS. On SQLite (tests) we PRAGMA-check.
    try:
        conn.execute(text(
            "ALTER TABLE bot_trades "
            "ADD COLUMN IF NOT EXISTS composite_score_at_execution INTEGER"
        ))
    except Exception as exc:
        # Fall back to a check-first pattern for older engines
        logger.warning("[m095] IF NOT EXISTS not supported, using check: %s", exc)
        try:
            probe = conn.execute(text(
                "SELECT composite_score_at_execution FROM bot_trades LIMIT 1"
            )).fetchone()
        except Exception:
            conn.execute(text(
                "ALTER TABLE bot_trades "
                "ADD COLUMN composite_score_at_execution INTEGER"
            ))

    if hasattr(conn, "commit"):
        conn.commit()

    logger.warning("[m095] added bot_trades.composite_score_at_execution")
    record(conn, _MIGRATION_NAME)
    return {"executed": True}
