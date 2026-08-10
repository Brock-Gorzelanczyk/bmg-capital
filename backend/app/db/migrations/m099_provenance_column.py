"""m099 — Provenance column on bot_trades + bot_positions (Brock 2026-08-10).

Structural fix for the class Brock has flagged 5 times: BMG-generated
rows (adopter, reconcile, rebuild, backfill) go into the same tables
as broker fills with no distinguishing marker. Every consumer treats
them as trades → phantom "today_pnl" on days with no trading, "trades"
while the market is shut.

This migration:
  1. Adds `origin TEXT` column (nullable initially so backfill can run).
  2. Backfills every existing row by inference from alpaca_order_id.
  3. Installs a SQLite trigger that REJECTs any INSERT/UPDATE leaving
     origin NULL or not in the allowed enum.
  4. Reports per-origin counts so any surprise surfaces immediately.

Values (see context/13-provenance-spec.md):
  BROKER_FILL — real Alpaca fill (36-char UUID alpaca_order_id).
                The ONLY value that counts as a "trade" for metrics.
  ADOPTED     — created by an adopter from an existing Alpaca position
  RECONCILE   — created/closed by reconciliation
  REBUILD     — created/updated by a rebuild job
  BACKFILL    — historical repair, dev scripts, migrations

Backfill inference order (first match wins):
  UUID shape           → BROKER_FILL
  starts with orphan_adopter/adopter/catchall_adopter_/adopt_missing_ → ADOPTED
  starts with reconcile_close_                                        → RECONCILE
  starts with rebuild_                                                → REBUILD
  everything else (incl. NULL)                                        → BACKFILL

The `catchall_double_count` / `admin_` / `autoflatten_` markers all
land in BACKFILL (repair operations, not fills).

CAUTION: this migration touches ~4,374 BotTrade rows + ~2,514 BotPosition
rows on prod. It's idempotent (guard by presence of `origin` column) but
takes ~10s on the /data volume. Run once at startup.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


_MIGRATION_NAME = "m099_provenance_column_2026_08_10"

# The ENUM enforced by the trigger (mirror in code: services/provenance.py).
_ALLOWED_ORIGINS = ("BROKER_FILL", "ADOPTED", "RECONCILE", "REBUILD", "BACKFILL")

# Backfill inference — SQL CASE expression applied to each row.
_BACKFILL_SQL = """
    CASE
        WHEN alpaca_order_id GLOB '????????-????-????-????-????????????'
             AND length(alpaca_order_id) = 36
        THEN 'BROKER_FILL'
        WHEN alpaca_order_id LIKE 'orphan_adopter%'
             OR alpaca_order_id LIKE 'adopter%'
             OR alpaca_order_id LIKE 'catchall_adopter_%'
             OR alpaca_order_id LIKE 'adopt_missing_%'
        THEN 'ADOPTED'
        WHEN alpaca_order_id LIKE 'reconcile_close_%'
        THEN 'RECONCILE'
        WHEN alpaca_order_id LIKE 'rebuild_%'
        THEN 'REBUILD'
        ELSE 'BACKFILL'
    END
"""


def _column_exists(conn, table: str, col: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == col for r in rows)


def _already_ran(conn) -> bool:
    try:
        row = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE name = :n"),
            {"n": _MIGRATION_NAME},
        ).fetchone()
        return row is not None
    except Exception:
        return False


def _record(conn) -> None:
    try:
        conn.execute(
            text("INSERT OR IGNORE INTO schema_migrations(name, applied_at) VALUES (:n, datetime('now'))"),
            {"n": _MIGRATION_NAME},
        )
    except Exception as exc:
        logger.warning("[m099] record failed: %s", exc)


def run(conn) -> dict:
    if _already_ran(conn):
        return {"skipped_reason": "already_applied", "executed": False}

    result: dict = {"executed": True, "steps": []}

    # ── 1. Add columns (nullable initially) ──────────────────────────────
    for table in ("bot_trades", "bot_positions"):
        if not _column_exists(conn, table, "origin"):
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN origin TEXT"))
            result["steps"].append(f"added {table}.origin column")
        else:
            result["steps"].append(f"{table}.origin already exists (skipping ALTER)")

    # ── 2. Backfill via inference ────────────────────────────────────────
    # bot_trades has alpaca_order_id — use CASE inference.
    conn.execute(text(
        f"UPDATE bot_trades SET origin = ({_BACKFILL_SQL}) WHERE origin IS NULL"
    ))
    # bot_positions has no alpaca_order_id column. Best signal: inherit from
    # the earliest linked bot_trade (via bot_trades.position_id = bot_positions.id).
    # Fall back to BACKFILL for orphan positions (no linked trade).
    conn.execute(text("""
        UPDATE bot_positions
           SET origin = COALESCE(
               (SELECT origin FROM bot_trades
                 WHERE bot_trades.position_id = bot_positions.id
                 ORDER BY bot_trades.ts ASC LIMIT 1),
               'BACKFILL'
           )
         WHERE origin IS NULL
    """))
    for table in ("bot_trades", "bot_positions"):
        counts_rows = conn.execute(text(
            f"SELECT origin, COUNT(*) FROM {table} GROUP BY origin ORDER BY 2 DESC"
        )).fetchall()
        counts = {(r[0] or "NULL"): int(r[1]) for r in counts_rows}
        result[f"{table}_counts_by_origin"] = counts

    # ── 3. Triggers — reject NULL / invalid origin on future writes ──────
    # Trigger drops + recreates so IF the ENUM ever changes we can re-run.
    allowed_sql = ", ".join(f"'{v}'" for v in _ALLOWED_ORIGINS)
    for table in ("bot_trades", "bot_positions"):
        conn.execute(text(f"DROP TRIGGER IF EXISTS {table}_require_origin_insert"))
        conn.execute(text(f"DROP TRIGGER IF EXISTS {table}_require_origin_update"))
        conn.execute(text(f"""
            CREATE TRIGGER {table}_require_origin_insert
            BEFORE INSERT ON {table}
            FOR EACH ROW
            WHEN NEW.origin IS NULL OR NEW.origin NOT IN ({allowed_sql})
            BEGIN
                SELECT RAISE(ABORT,
                    '{table}: origin must be one of {allowed_sql} (m099)');
            END
        """))
        conn.execute(text(f"""
            CREATE TRIGGER {table}_require_origin_update
            BEFORE UPDATE ON {table}
            FOR EACH ROW
            WHEN NEW.origin IS NULL OR NEW.origin NOT IN ({allowed_sql})
            BEGIN
                SELECT RAISE(ABORT,
                    '{table}: origin update must be one of {allowed_sql} (m099)');
            END
        """))
        result["steps"].append(f"installed {table}_require_origin_insert/update triggers")

    # ── 4. Index on origin for fast consumer filtering ───────────────────
    for table in ("bot_trades", "bot_positions"):
        conn.execute(text(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_origin ON {table}(origin)"
        ))
    result["steps"].append("created origin indexes on both tables")

    if hasattr(conn, "commit"):
        conn.commit()

    _record(conn)
    logger.warning(
        "[m099] provenance column shipped — bot_trades: %s, bot_positions: %s",
        result.get("bot_trades_counts_by_origin"),
        result.get("bot_positions_counts_by_origin"),
    )
    return result
