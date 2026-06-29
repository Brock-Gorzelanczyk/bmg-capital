"""m036 — agent_commitments table (action items with 3-strikes escalation).

NOTE: Archival job needed when row count > 10k. Out of scope for v1.
Commitment status transitions: open → done | broken | cancelled.
Only 'done'/'cancelled' transitions are set via future POST endpoint
(not implemented in v1 — manual SQL UPDATE for now).
"""
from __future__ import annotations

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

_NAME = "m036_agent_commitments_2026_06"

_DDL = """
CREATE TABLE IF NOT EXISTS agent_commitments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id          TEXT NOT NULL,
    owner_agent         TEXT NOT NULL,
    action_description  TEXT NOT NULL,
    deadline            TIMESTAMP NOT NULL,
    status              TEXT NOT NULL DEFAULT 'open',
    resolved_at         TIMESTAMP,
    resolution_note     TEXT,
    strike_count        INTEGER NOT NULL DEFAULT 0,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_IDXS = [
    "CREATE INDEX IF NOT EXISTS idx_commitments_owner_status ON agent_commitments(owner_agent, status)",
    "CREATE INDEX IF NOT EXISTS idx_commitments_deadline     ON agent_commitments(deadline)",
    "CREATE INDEX IF NOT EXISTS idx_commitments_meeting      ON agent_commitments(meeting_id)",
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
