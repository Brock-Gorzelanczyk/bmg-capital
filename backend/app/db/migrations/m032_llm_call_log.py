"""m032 — Audit log for every LLM call (relay, api_fallback, cache)."""
from __future__ import annotations
import logging
from sqlalchemy import text
from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)
_NAME = "m032_llm_call_log_2026_06"

_DDL = """
CREATE TABLE IF NOT EXISTS llm_call_log (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    agent_name            TEXT NOT NULL,
    model                 TEXT NOT NULL,
    prompt_chars          INTEGER NOT NULL,
    response_chars        INTEGER NOT NULL,
    source                TEXT NOT NULL CHECK(source IN ('relay','api_fallback','cache')),
    duration_ms           INTEGER NOT NULL DEFAULT 0,
    estimated_cost_cents  INTEGER NOT NULL DEFAULT 0,
    error                 TEXT
);
"""
_IDX_CREATED = "CREATE INDEX IF NOT EXISTS idx_llm_log_created ON llm_call_log(created_at);"
_IDX_SOURCE  = "CREATE INDEX IF NOT EXISTS idx_llm_log_source  ON llm_call_log(source);"
_IDX_AGENT   = "CREATE INDEX IF NOT EXISTS idx_llm_log_agent   ON llm_call_log(agent_name);"


def run(conn) -> dict:
    if already_ran(conn, _NAME):
        return {"skipped_reason": "already_applied", "executed": False}
    conn.execute(text(_DDL))
    conn.execute(text(_IDX_CREATED))
    conn.execute(text(_IDX_SOURCE))
    conn.execute(text(_IDX_AGENT))
    conn.commit()
    record(conn, _NAME)
    return {"executed": True}
