"""m030 — Add inception_capital_cents_snapshot + note column to bot_daily_pnl.

Creates archive tables and backfills snapshot from current inception_capital_cents.
No DELETE, no UPDATE to inception_capital_cents, no wipe of bot_trades/bot_daily_pnl.

SHIP 3 standing decision: capital resets must never delete trade history.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_GATE_NAME = "m030_inception_snapshot_on_daily_pnl_2026_06"


def _table_exists(conn, table: str) -> bool:
    row = conn.execute(
        text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
        {"t": table},
    ).fetchone()
    return row is not None


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def run(conn) -> dict:
    """Return shape:
        {"executed": bool, "skipped_reason": str | None,
         "column_added": bool, "note_column_added": bool,
         "backfilled_rows": int, "archive_tables_created": int}
    """
    if already_ran(conn, _GATE_NAME):
        return {"executed": False, "skipped_reason": "already_applied",
                "column_added": False, "note_column_added": False,
                "backfilled_rows": 0, "archive_tables_created": 0}

    if not _table_exists(conn, "bot_daily_pnl"):
        return {"executed": False, "skipped_reason": "bot_daily_pnl missing",
                "column_added": False, "note_column_added": False,
                "backfilled_rows": 0, "archive_tables_created": 0}

    column_added = False
    note_column_added = False
    archive_tables_created = 0

    # 1. Add inception_capital_cents_snapshot column if missing.
    # Use try/except to handle re-runs on a DB where the column already exists
    # (SQLite raises OperationalError: duplicate column name on a second ADD).
    if not _column_exists(conn, "bot_daily_pnl", "inception_capital_cents_snapshot"):
        try:
            conn.execute(text(
                "ALTER TABLE bot_daily_pnl "
                "ADD COLUMN inception_capital_cents_snapshot INTEGER NOT NULL DEFAULT 0"
            ))
            column_added = True
            logger.info("[m030] Added inception_capital_cents_snapshot column to bot_daily_pnl")
        except Exception as exc:
            # Column already exists (e.g. prior failed run in production).
            logger.warning("[m030] ADD COLUMN inception_capital_cents_snapshot skipped: %s", exc)

    # 2. Add note column if missing (used for track_reset_marker rows)
    if not _column_exists(conn, "bot_daily_pnl", "note"):
        conn.execute(text(
            "ALTER TABLE bot_daily_pnl ADD COLUMN note TEXT"
        ))
        note_column_added = True
        logger.info("[m030] Added note column to bot_daily_pnl")

    # 3. Backfill snapshot where still 0 (additive, no overwrite of nonzero values)
    #    Guard: only if bot_allocations.inception_capital_cents column exists
    has_inception_col = (
        _table_exists(conn, "bot_allocations")
        and _column_exists(conn, "bot_allocations", "inception_capital_cents")
    )

    if has_inception_col:
        conn.execute(text("""
            UPDATE bot_daily_pnl
               SET inception_capital_cents_snapshot = COALESCE(
                   (SELECT inception_capital_cents
                      FROM bot_allocations
                     WHERE bot_allocations.id = bot_daily_pnl.allocation_id),
                   0
               )
             WHERE inception_capital_cents_snapshot = 0
        """))
    else:
        # fallback: inception column missing, use starting_capital_cents only
        if _column_exists(conn, "bot_allocations", "starting_capital_cents"):
            conn.execute(text("""
                UPDATE bot_daily_pnl
                   SET inception_capital_cents_snapshot = COALESCE(
                       (SELECT starting_capital_cents
                          FROM bot_allocations
                         WHERE bot_allocations.id = bot_daily_pnl.allocation_id),
                       0
                   )
                 WHERE inception_capital_cents_snapshot = 0
            """))

    backfilled = conn.execute(
        text("SELECT COUNT(*) FROM bot_daily_pnl WHERE inception_capital_cents_snapshot != 0")
    ).fetchone()[0] or 0

    # 4. Create archive tables (additive, SQLite AS SELECT WHERE 0 pattern)
    for archive_table, source_table in [
        ("bot_trades_archive", "bot_trades"),
        ("bot_daily_pnl_archive", "bot_daily_pnl"),
    ]:
        if not _table_exists(conn, archive_table) and _table_exists(conn, source_table):
            conn.execute(text(
                f"CREATE TABLE IF NOT EXISTS {archive_table} "
                f"AS SELECT * FROM {source_table} WHERE 0"
            ))
            # Add archived_at column for preservation timestamp
            conn.execute(text(
                f"ALTER TABLE {archive_table} ADD COLUMN archived_at TEXT"
            ))
            archive_tables_created += 1
            logger.info("[m030] Created archive table %s", archive_table)

    conn.commit()
    record(conn, _GATE_NAME)

    logger.info(
        "[m030] Done: column_added=%s note_added=%s backfilled=%d archives=%d",
        column_added, note_column_added, backfilled, archive_tables_created,
    )

    return {
        "executed": True,
        "skipped_reason": None,
        "column_added": column_added,
        "note_column_added": note_column_added,
        "backfilled_rows": backfilled,
        "archive_tables_created": archive_tables_created,
    }
