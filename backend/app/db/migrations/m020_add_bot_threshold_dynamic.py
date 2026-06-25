"""m020 — Add `bot_threshold_dynamic` table for auto-promote overrides.

Populated nightly by strategy_lab.bot_scheduler.run_threshold_auto_promote.
Each row carries the dynamically computed composite_threshold + the basis
(rolling 30-day Sharpe + trade count) + the source tag so a discipline
audit can always trace why a profile is on a non-default threshold.

The discipline filter resolves thresholds with precedence:
  dynamic (this table) → YAML override → strategy override → profile → 60

Idempotent — skips if the table already exists.
"""
from __future__ import annotations

import logging

from sqlalchemy import text

logger = logging.getLogger(__name__)


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return bool(rows)


def run(conn) -> dict:
    if _table_exists(conn, "bot_threshold_dynamic"):
        logger.info("[m020] bot_threshold_dynamic already exists — no-op")
        return {"added": []}

    conn.execute(text("""
        CREATE TABLE bot_threshold_dynamic (
            profile_id     INTEGER PRIMARY KEY,
            threshold      INTEGER NOT NULL,
            sharpe_30d     REAL,
            trade_count    INTEGER,
            source         TEXT,
            updated_at     DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.commit()
    logger.info("[m020] created bot_threshold_dynamic table")
    return {"added": ["bot_threshold_dynamic"]}
