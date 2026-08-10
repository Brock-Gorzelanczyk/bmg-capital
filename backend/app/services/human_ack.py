"""REQUIRES_HUMAN_ACK — pending-action ledger.

Brock 2026-08-10: any auto-action creates an ack record. Pre-market and
close reports LEAD with unacked items. Scans_gate resume refuses when
any unacked ack blocks it.

The point: an autonomous action isn't complete until a human has seen
and acknowledged the state change. Silent auto-actions caused the
Monday-morning loop failure.

Categories map 1:1 with critical_alert.CATEGORIES:
  AUTO_PAUSE, INVARIANT_RED_STALE, DISK_HIGH, SIM_FILL_DETECTED

The (category, ref_key) tuple is unique so re-firing an existing
condition doesn't create duplicate acks.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


def ensure_table(conn) -> None:
    """Idempotent — creates table if missing. Called from startup migration."""
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS human_ack_required (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            ref_key TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT,
            created_at TEXT NOT NULL,
            created_by TEXT NOT NULL,
            acknowledged_at TEXT,
            acknowledged_by TEXT,
            UNIQUE(category, ref_key)
        )
    """))
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_human_ack_open "
        "ON human_ack_required(category) WHERE acknowledged_at IS NULL"
    ))


def create(
    db,
    *,
    category: str,
    ref_key: str,
    title: str,
    body: str = "",
    created_by: str,
) -> Optional[int]:
    """Create an ack record. Idempotent on (category, ref_key) — re-firing
    the same condition returns the existing id without a new row.
    Returns the row id, or None on error."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        db.execute(text(
            "INSERT OR IGNORE INTO human_ack_required "
            "(category, ref_key, title, body, created_at, created_by) "
            "VALUES (:c, :r, :t, :b, :ts, :cb)"
        ), {"c": category, "r": ref_key, "t": title, "b": body, "ts": now, "cb": created_by})
        row = db.execute(text(
            "SELECT id FROM human_ack_required WHERE category = :c AND ref_key = :r"
        ), {"c": category, "r": ref_key}).fetchone()
        db.commit()
        return int(row[0]) if row else None
    except Exception as exc:
        logger.warning("[human-ack] create failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


def acknowledge(db, *, ack_id: int, by: str) -> bool:
    """Mark an ack as acknowledged. Returns True if it flipped, False if
    already-acked or not found."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        result = db.execute(text(
            "UPDATE human_ack_required "
            "SET acknowledged_at = :ts, acknowledged_by = :by "
            "WHERE id = :id AND acknowledged_at IS NULL"
        ), {"ts": now, "by": by, "id": ack_id})
        db.commit()
        return (result.rowcount or 0) > 0
    except Exception as exc:
        logger.warning("[human-ack] acknowledge failed: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return False


def list_unacked(db, category: Optional[str] = None) -> list[dict]:
    """Return all unacknowledged acks. Optionally filter by category."""
    try:
        if category:
            rows = db.execute(text(
                "SELECT id, category, ref_key, title, body, created_at, created_by "
                "FROM human_ack_required "
                "WHERE acknowledged_at IS NULL AND category = :c "
                "ORDER BY created_at DESC"
            ), {"c": category}).fetchall()
        else:
            rows = db.execute(text(
                "SELECT id, category, ref_key, title, body, created_at, created_by "
                "FROM human_ack_required "
                "WHERE acknowledged_at IS NULL "
                "ORDER BY created_at DESC"
            )).fetchall()
        return [
            {"id": r[0], "category": r[1], "ref_key": r[2], "title": r[3],
             "body": r[4], "created_at": r[5], "created_by": r[6]}
            for r in rows
        ]
    except Exception as exc:
        logger.warning("[human-ack] list_unacked failed: %s", exc)
        return []


def count_unacked(db, category: Optional[str] = None) -> int:
    """Fast count."""
    try:
        if category:
            row = db.execute(text(
                "SELECT COUNT(*) FROM human_ack_required "
                "WHERE acknowledged_at IS NULL AND category = :c"
            ), {"c": category}).fetchone()
        else:
            row = db.execute(text(
                "SELECT COUNT(*) FROM human_ack_required "
                "WHERE acknowledged_at IS NULL"
            )).fetchone()
        return int(row[0] or 0)
    except Exception:
        return 0
