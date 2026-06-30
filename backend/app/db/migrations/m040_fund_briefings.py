"""m034 — fund_briefings table (rendered markdown briefings)."""
from __future__ import annotations

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

_NAME = "m040_fund_briefings_2026_06"

_DDL = """
CREATE TABLE IF NOT EXISTS fund_briefings (
    briefing_id         TEXT PRIMARY KEY,
    meeting_id          TEXT NOT NULL,
    markdown_body       TEXT NOT NULL,
    summary_one_liner   TEXT NOT NULL DEFAULT '',
    needs_brock         INTEGER NOT NULL DEFAULT 0,
    posted_at           TIMESTAMP,
    discord_message_id  TEXT,
    created_at          TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""

_IDXS = [
    "CREATE INDEX IF NOT EXISTS idx_fund_briefings_meeting_id ON fund_briefings(meeting_id)",
    "CREATE INDEX IF NOT EXISTS idx_fund_briefings_created_at ON fund_briefings(created_at)",
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
