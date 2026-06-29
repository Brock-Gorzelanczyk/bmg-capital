"""m038 — bot_symbol_cooldown table for SHIP 6 hard 24h clamp.

NOTE for future clean-slate migrations: if a clean-slate wipe is ever added
(like m027), it should also DELETE FROM bot_symbol_cooldown WHERE bot_id IN (...)
to clear stale cooldown rows for reset bots. Not scoped in SHIP 6.
"""
from __future__ import annotations
import logging
from sqlalchemy import text
from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)
_NAME = "m038_bot_symbol_cooldown_2026_06"

_DDL = """
CREATE TABLE IF NOT EXISTS bot_symbol_cooldown (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id            TEXT NOT NULL,
    symbol            TEXT NOT NULL,
    cooldown_until    TIMESTAMP NOT NULL,
    last_entry_at     TIMESTAMP NOT NULL,
    created_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""
_IDX_UNIQUE = """
CREATE UNIQUE INDEX IF NOT EXISTS uix_bot_symbol_cooldown_botsym
    ON bot_symbol_cooldown(bot_id, symbol);
"""
_IDX_CD_UNTIL = """
CREATE INDEX IF NOT EXISTS idx_bot_symbol_cooldown_until
    ON bot_symbol_cooldown(cooldown_until);
"""


def run(conn) -> dict:
    if already_ran(conn, _NAME):
        return {"skipped_reason": "already_applied", "executed": False}
    conn.execute(text(_DDL))
    conn.execute(text(_IDX_UNIQUE))
    conn.execute(text(_IDX_CD_UNTIL))
    conn.commit()
    record(conn, _NAME)
    return {"executed": True}
