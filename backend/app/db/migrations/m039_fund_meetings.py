"""m033 — fund_meetings table (CIO Morning Meeting orchestrator)."""
from __future__ import annotations

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

_NAME = "m039_fund_meetings_2026_06"

_DDL = """
CREATE TABLE IF NOT EXISTS fund_meetings (
    meeting_id          TEXT PRIMARY KEY,
    started_at          TIMESTAMP NOT NULL,
    ended_at            TIMESTAMP,
    duration_seconds    INTEGER,
    model_cost_usd      REAL NOT NULL DEFAULT 0.0,
    briefing_id         TEXT,
    vetoes_used         INTEGER NOT NULL DEFAULT 0,
    status              TEXT NOT NULL DEFAULT 'running',
    failure_reason      TEXT,
    created_by_runner   TEXT
)
"""

_IDXS = [
    "CREATE INDEX IF NOT EXISTS idx_fund_meetings_started_at ON fund_meetings(started_at)",
    "CREATE INDEX IF NOT EXISTS idx_fund_meetings_status     ON fund_meetings(status)",
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
