"""m028 — Snapshot existing cross-sleeve violations into a quarantine table.

INERT migration: CREATE TABLE + INSERT into its own new table only.
Does NOT UPDATE or DELETE from bot_allocations, bot_trades, bot_daily_pnl,
or bot_positions. (Hard Constraint 4 / SHIP 2 standing decisions.)

Per-row review by Brock is a separate ship.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record
from app.services.asset_class_registry import (
    get_required_asset_class,
    classify_instrument,
)

logger = logging.getLogger(__name__)

_NAME = "m028_quarantine_cross_sleeve_2026_06"
TARGET_USER_ID = 1

_DDL = """
CREATE TABLE IF NOT EXISTS cross_sleeve_quarantine_s14 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER NOT NULL,
    bot_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    declared_asset_class TEXT NOT NULL,
    actual_symbol TEXT NOT NULL,
    actual_asset_class TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'review',
    resolved_at TEXT,
    resolution_note TEXT
)
"""
_UNIQUE_IDX_DDL = (
    "CREATE UNIQUE INDEX IF NOT EXISTS "
    "ux_cross_sleeve_quarantine_s14_position ON cross_sleeve_quarantine_s14(position_id)"
)


def run(conn) -> dict:
    """Idempotent: uses _gate to short-circuit on subsequent boots."""
    if already_ran(conn, _NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    conn.execute(text(_DDL))
    conn.execute(text(_UNIQUE_IDX_DDL))
    conn.commit()

    # Scan only user 1, only OPEN positions, only non-quarantined.
    rows = conn.execute(text("""
        SELECT pos.id, pos.symbol, prof.name AS bot_id
          FROM bot_positions pos
          JOIN bot_allocations a ON a.id = pos.allocation_id
          JOIN bot_profiles prof ON prof.id = a.profile_id
         WHERE a.user_id = :uid
           AND pos.closed_at IS NULL
           AND pos.quarantined_at IS NULL
    """), {"uid": TARGET_USER_ID}).fetchall()

    inserted = 0
    skipped_unclassifiable = 0
    now = datetime.now(timezone.utc).isoformat()
    for r in rows:
        pos_id = int(r[0])
        symbol = r[1]
        bot_id = r[2]
        try:
            required = get_required_asset_class(bot_id)
            actual = classify_instrument(symbol)
        except RuntimeError as exc:
            # Unknown bot_id (e.g., legacy bot not in m027 spec) OR
            # unclassifiable symbol: skip + log — avoids false positives.
            logger.warning(
                "[m028] skip unclassifiable: bot=%s symbol=%s err=%s",
                bot_id, symbol, exc,
            )
            skipped_unclassifiable += 1
            continue

        if required == actual:
            continue

        # INSERT OR IGNORE on the unique index makes this idempotent across
        # forced re-runs (race-safe: UNIQUE on position_id).
        conn.execute(text("""
            INSERT OR IGNORE INTO cross_sleeve_quarantine_s14
                (position_id, bot_id, user_id, declared_asset_class,
                 actual_symbol, actual_asset_class, detected_at, action)
            VALUES (:pid, :bid, :uid, :dac, :sym, :aac, :ts, 'review')
        """), {
            "pid": pos_id,
            "bid": bot_id,
            "uid": TARGET_USER_ID,
            "dac": required,
            "sym": symbol,
            "aac": actual,
            "ts": now,
        })
        inserted += 1

    conn.commit()
    record(conn, _NAME)
    return {
        "executed": True,
        "user_id": TARGET_USER_ID,
        "rows_scanned": len(rows),
        "quarantined": inserted,
        "skipped_unclassifiable": skipped_unclassifiable,
    }
