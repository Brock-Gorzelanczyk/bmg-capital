"""m028 — Quarantine existing cross-sleeve open positions for user_id=1.

What this migration does:
  1. Creates cross_sleeve_quarantine_s14 table + indexes (additive, no drops).
  2. Scans all currently OPEN bot_positions for user_id=1 ONLY.
     Open = closed_at IS NULL AND quarantined_at IS NULL.
  3. For each position, checks if the bot's declared asset_class matches
     classify_instrument(symbol). Also checks cash_floor ticker_allowlist.
  4. Violations are inserted into cross_sleeve_quarantine_s14 with action='review'.
  5. NO positions are auto-closed. Brock reviews per row (mass-action restraint,
     decision-history.md).

Re-run safety:
  - schema_migrations key makes this one-shot.
  - INSERT OR IGNORE + unique index on position_id make scanning idempotent.

Post-m028, new violations CANNOT occur because COMMIT 2 hard-blocks all
10 order-placement paths. The scope is "open NOW positions at migration time"
— no date predicate needed (known-issues #8 trap applies to migrations that
run on every boot; m028 is one-shot).

Multi-user safe: every write carries WHERE user_id = 1.
Do NOT scan user_id != 1. user_id=3 has separate test allocations.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

TARGET_USER_ID = 1
_MIGRATION_NAME = "m028_quarantine_cross_sleeve"

_DDL_TABLE = """
CREATE TABLE IF NOT EXISTS cross_sleeve_quarantine_s14 (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id           INTEGER NOT NULL,
    bot_id                TEXT NOT NULL,
    user_id               INTEGER NOT NULL,
    declared_asset_class  TEXT NOT NULL,
    actual_symbol         TEXT NOT NULL,
    actual_asset_class    TEXT NOT NULL,
    detected_at           TIMESTAMP NOT NULL,
    action                TEXT NOT NULL DEFAULT 'review',
    resolved_at           TIMESTAMP,
    resolution_note       TEXT
)
"""

_DDL_IDX_UNRESOLVED = """
CREATE INDEX IF NOT EXISTS idx_cs_quarantine_unresolved
    ON cross_sleeve_quarantine_s14 (resolved_at, detected_at DESC)
"""

_DDL_IDX_POS_UNIQUE = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_cs_quarantine_pos_unique
    ON cross_sleeve_quarantine_s14 (position_id)
"""


def _migration_already_ran(conn, name: str) -> bool:
    try:
        return conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"),
            {"n": name},
        ).fetchone() is not None
    except Exception:
        return False


def _record_migration(conn, name: str) -> None:
    conn.execute(
        text("INSERT INTO schema_migrations (migration_name) VALUES (:n)"
             " ON CONFLICT (migration_name) DO NOTHING"),
        {"n": name},
    )
    conn.commit()


def run(conn) -> dict:
    if _migration_already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    # Create table + indexes (DDL above)
    conn.execute(text(_DDL_TABLE))
    conn.execute(text(_DDL_IDX_UNRESOLVED))
    conn.execute(text(_DDL_IDX_POS_UNIQUE))
    conn.commit()

    # Scan all currently OPEN bot_positions for user_id=1 ONLY.
    # Open = closed_at IS NULL AND quarantined_at IS NULL.
    rows = conn.execute(text("""
        SELECT bp.id, p.name AS bot_id, ba.user_id, bp.symbol
          FROM bot_positions bp
          JOIN bot_allocations ba ON ba.id = bp.allocation_id
          JOIN bot_profiles    p  ON p.id  = ba.profile_id
         WHERE ba.user_id    = :uid
           AND bp.closed_at  IS NULL
           AND bp.quarantined_at IS NULL
    """), {"uid": TARGET_USER_ID}).fetchall()

    from app.services.asset_class_registry import (
        get_required_asset_class, classify_instrument, get_ticker_allowlist,
    )

    quarantined = 0
    skipped_unknown = 0
    now_iso = datetime.now(timezone.utc).isoformat()
    for r in rows:
        pos_id = int(r[0])
        bot_id = r[1]
        user_id = int(r[2])
        symbol = r[3] or ""

        try:
            required = get_required_asset_class(bot_id)
        except RuntimeError:
            # Bot not in registry (e.g., retired bot still has stragglers).
            # Skip — quarantine is for cross-sleeve enforcement, not orphan cleanup.
            skipped_unknown += 1
            continue

        try:
            actual = classify_instrument(symbol)
        except RuntimeError:
            # Unclassifiable symbol — treat as a violation, label actual="unknown".
            actual = "unknown"

        is_class_mismatch = actual != required and actual != "unknown"
        allowlist = None
        try:
            allowlist = get_ticker_allowlist(bot_id)
        except RuntimeError:
            pass
        is_allowlist_violation = (
            allowlist is not None
            and symbol.strip().upper() not in [t.upper() for t in allowlist]
        )

        if not (is_class_mismatch or actual == "unknown" or is_allowlist_violation):
            continue

        conn.execute(text("""
            INSERT OR IGNORE INTO cross_sleeve_quarantine_s14
                (position_id, bot_id, user_id, declared_asset_class,
                 actual_symbol, actual_asset_class, detected_at, action)
            VALUES (:pid, :bid, :uid, :decl, :sym, :act, :ts, 'review')
        """), {
            "pid": pos_id, "bid": bot_id, "uid": user_id,
            "decl": required, "sym": symbol, "act": actual, "ts": now_iso,
        })
        quarantined += 1

    conn.commit()
    _record_migration(conn, _MIGRATION_NAME)
    logger.warning("[m028] quarantined=%d skipped_unknown_bot=%d", quarantined, skipped_unknown)
    return {"executed": True, "quarantined": quarantined, "skipped_unknown_bot": skipped_unknown}
