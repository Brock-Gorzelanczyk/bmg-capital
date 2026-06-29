"""m037 — veto_log table (Dick CRO veto decisions + Brock override log)."""
from __future__ import annotations

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

_NAME = "m037_veto_log_2026_06"

_DDL = """
CREATE TABLE IF NOT EXISTS veto_log (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id              TEXT NOT NULL,
    vetoed_by               TEXT NOT NULL,
    vetoed_target_proposal  TEXT NOT NULL,
    reason                  TEXT NOT NULL,
    brock_override          INTEGER NOT NULL DEFAULT 0,
    override_at             TIMESTAMP,
    override_note           TEXT,
    created_at              TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_IDXS = [
    "CREATE INDEX IF NOT EXISTS idx_veto_log_meeting  ON veto_log(meeting_id)",
    "CREATE INDEX IF NOT EXISTS idx_veto_log_override ON veto_log(brock_override)",
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
