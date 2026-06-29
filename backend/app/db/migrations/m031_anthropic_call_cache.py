"""m031 — Cache table for LLM responses keyed by sha256(model||system||prompt||extra)."""
from __future__ import annotations
import logging
from sqlalchemy import text
from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)
_NAME = "m031_anthropic_call_cache_2026_06"

_DDL = """
CREATE TABLE IF NOT EXISTS anthropic_call_cache (
    cache_key       TEXT PRIMARY KEY,
    model           TEXT NOT NULL,
    prompt_hash     TEXT NOT NULL,
    response_json   TEXT NOT NULL,
    response_text   TEXT NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      TIMESTAMP NOT NULL,
    hit_count       INTEGER NOT NULL DEFAULT 0,
    last_hit_at     TIMESTAMP
);
"""
_IDX = "CREATE INDEX IF NOT EXISTS idx_acc_expires ON anthropic_call_cache(expires_at);"


def run(conn) -> dict:
    if already_ran(conn, _NAME):
        return {"skipped_reason": "already_applied", "executed": False}
    conn.execute(text(_DDL))
    conn.execute(text(_IDX))
    conn.commit()
    record(conn, _NAME)
    return {"executed": True}
