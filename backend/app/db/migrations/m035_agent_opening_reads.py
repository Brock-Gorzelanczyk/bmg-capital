"""m035 — agent_opening_reads table (per-agent structured opening read per meeting)."""
from __future__ import annotations

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

_NAME = "m035_agent_opening_reads_2026_06"

_DDL = """
CREATE TABLE IF NOT EXISTS agent_opening_reads (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id              TEXT NOT NULL,
    agent_name              TEXT NOT NULL,
    structured_read_json    TEXT NOT NULL,
    response_time_ms        INTEGER NOT NULL DEFAULT 0,
    cost_usd                REAL NOT NULL DEFAULT 0.0,
    status                  TEXT NOT NULL,
    error_text              TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(meeting_id, agent_name)
)
"""

_IDXS = [
    "CREATE INDEX IF NOT EXISTS idx_opening_reads_meeting ON agent_opening_reads(meeting_id)",
    "CREATE INDEX IF NOT EXISTS idx_opening_reads_agent   ON agent_opening_reads(agent_name)",
]


def run(conn) -> dict:
    if already_ran(conn, _NAME):
        return {"skipped_reason": "already_applied", "executed": False}
    conn.execute(text(_DDL))
    for idx in _IDXS:
        conn.execute(text(idx))
    conn.commit()
    record(conn, _NAME)
    return {"executed": True, "migration": _NAME}
