"""m102 — confluence_picks arm state (Brock 2026-08-20).

Adds the fields needed for the confluence executor to auto-fire bracket
orders when Play A / Play B triggers hit. Prior to m102 a pick was
journaling-only; m102 makes it executable.

**New columns on `confluence_picks`:**
  arm_state              — LOGGED | ARMED | FILLED_A | FILLED_B | EXPIRED | DISARMED
  arm_mode               — play_a_only | play_b_only | either
  arm_expires_at         — ISO datetime (UTC). null = no expiry.
  size_dollars_cents     — position size in cents (default 500000 = $5K)
  play_a_trigger_price_cents
  play_a_stop_price_cents
  play_a_volume_multiple — default 1.2 (breakout vs 20d avg volume)
  play_b_trigger_price_cents
  play_b_stop_price_cents
  target_1_cents         — first profit target (100% out here for MVP)
  target_2_cents         — second target (not used in MVP)
  alpaca_bracket_order_id — parent order id after fire
  filled_at              — ISO datetime the fire happened
  filled_price_cents     — actual fill price

Idempotent (checks column existence before ALTER).
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m102_confluence_arm_2026_08_20"


def _already_ran(conn) -> bool:
    try:
        row = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :n"),
            {"n": _MIGRATION_NAME},
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _column_exists(conn, table: str, col: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def _add_col_if_missing(conn, table: str, col_def: str) -> None:
    col_name = col_def.split()[0]
    if not _column_exists(conn, table, col_name):
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_def}"))


def run(conn) -> dict:
    if _already_ran(conn):
        return {"status": "skip", "reason": "already_ran"}

    tbl = "confluence_picks"

    _add_col_if_missing(conn, tbl, "arm_state TEXT DEFAULT 'LOGGED'")
    _add_col_if_missing(conn, tbl, "arm_mode TEXT")
    _add_col_if_missing(conn, tbl, "arm_expires_at TEXT")
    _add_col_if_missing(conn, tbl, "size_dollars_cents INTEGER DEFAULT 500000")
    _add_col_if_missing(conn, tbl, "play_a_trigger_price_cents INTEGER")
    _add_col_if_missing(conn, tbl, "play_a_stop_price_cents INTEGER")
    _add_col_if_missing(conn, tbl, "play_a_volume_multiple REAL DEFAULT 1.2")
    _add_col_if_missing(conn, tbl, "play_b_trigger_price_cents INTEGER")
    _add_col_if_missing(conn, tbl, "play_b_stop_price_cents INTEGER")
    _add_col_if_missing(conn, tbl, "target_1_cents INTEGER")
    _add_col_if_missing(conn, tbl, "target_2_cents INTEGER")
    _add_col_if_missing(conn, tbl, "alpaca_bracket_order_id TEXT")
    _add_col_if_missing(conn, tbl, "filled_at TEXT")
    _add_col_if_missing(conn, tbl, "filled_price_cents INTEGER")

    # Index for the executor's hot query: WHERE arm_state='ARMED'
    conn.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_confluence_armed "
        "ON confluence_picks(arm_state) WHERE arm_state='ARMED'"
    ))

    try:
        conn.execute(
            text("INSERT OR IGNORE INTO schema_migrations (name) VALUES (:n)"),
            {"n": _MIGRATION_NAME},
        )
    except Exception as e:
        logger.warning("[m102] schema_migrations write failed: %s", e)

    return {"status": "ok", "added": 14, "table": tbl}
