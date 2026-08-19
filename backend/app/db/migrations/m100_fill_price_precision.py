"""m100 — fill_price_micros column on bot_trades (ledger #34).

Structural fix for the sub-penny fill precision bug.

bot_trades.fill_price_cents is declared Float in the ORM but every writer
coerces with `int(round(px * 100))`. For SHIB @ $0.000024 that becomes
`int(round(0.0024))` = 0. So SHIB / BONK / PEPE fills record $0, and
realized-P&L math treats them as free — inflating bot P&L by whatever
the sub-penny leg was worth. I26 flags 46 rows in this state as of
2026-08-18.

This migration:
  1. Adds `fill_price_micros BIGINT` column (nullable — writers migrate
     in a separate commit; consumers migrate in a follow-on PR).
  2. Backfills every existing non-null, non-zero fill_price_cents by
     `micros = CAST(cents * 10_000 AS BIGINT)`. Lossless for the ~4,328
     non-sub-penny rows.
  3. LEAVES the 46 known-broken sub-penny rows NULL — that's the marker
     for the Alpaca-backfill script (scripts/backfill_fill_price_micros.py)
     to hit next.
  4. Creates index for query patterns that filter on the new column.
  5. Reports per-bucket counts so any surprise surfaces immediately.

Does NOT install a NOT NULL trigger (writers migrate in a separate PR
per §S28 chokepoint discipline — a trigger firing before writers land
would crash every BotTrade insert). Does NOT drop fill_price_cents
(m101 handles that after 30 days of parallel-write + all consumers
green on the new field).

Reference: .pipeline/01-spec.md (agent-authored 2026-08-18).
Related: ledger #34, invariant I26 (interim guard), invariant I29 (new,
follow-on commit — asserts fill_price_micros IS NULL AND origin='BROKER_FILL'
AND qty > 0 → count == 0).

CAUTION: Touches ~4,374 BotTrade rows on prod. ALTER TABLE + backfill
take ~10s on the /data volume. Idempotent (guard by presence of
fill_price_micros column + schema_migrations row).
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


_MIGRATION_NAME = "m100_fill_price_precision_2026_08_18"


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
        logger.warning("[m100] record failed: %s", exc)


def run(conn) -> dict:
    if _already_ran(conn):
        return {"skipped_reason": "already_applied", "executed": False}

    result: dict = {"executed": True, "steps": []}

    # ── 1. Add column (nullable) ──────────────────────────────────────────
    if not _column_exists(conn, "bot_trades", "fill_price_micros"):
        conn.execute(text(
            "ALTER TABLE bot_trades ADD COLUMN fill_price_micros BIGINT"
        ))
        result["steps"].append("added bot_trades.fill_price_micros column")
    else:
        result["steps"].append("fill_price_micros already exists (skipping ALTER)")

    # ── 2. Counts BEFORE (so we can diff after) ──────────────────────────
    counts_before = {}
    for label, sql in (
        ("total_rows", "SELECT COUNT(*) FROM bot_trades"),
        ("non_null_cents",
         "SELECT COUNT(*) FROM bot_trades WHERE fill_price_cents IS NOT NULL"),
        ("zero_cents_broker_fills",
         "SELECT COUNT(*) FROM bot_trades WHERE fill_price_cents = 0 "
         "AND origin = 'BROKER_FILL' AND qty > 0"),
        ("null_micros_before",
         "SELECT COUNT(*) FROM bot_trades WHERE fill_price_micros IS NULL"),
    ):
        try:
            counts_before[label] = int(conn.execute(text(sql)).scalar() or 0)
        except Exception as exc:
            counts_before[label] = f"query_failed:{exc}"
    result["counts_before"] = counts_before

    # ── 3. Backfill from cents where possible (loss-less for non-sub-penny) ──
    # We multiply by 10_000 because 1 cent = 10_000 micros (1e6 / 100).
    # Skip zeros — those are either legitimately zero (rare) or the sub-penny
    # bug marker. The sub-penny bug rows are handled by the Alpaca backfill
    # script in step 5 of the spec.
    r = conn.execute(text(
        "UPDATE bot_trades "
        "   SET fill_price_micros = CAST(fill_price_cents * 10000 AS BIGINT) "
        " WHERE fill_price_micros IS NULL "
        "   AND fill_price_cents IS NOT NULL "
        "   AND fill_price_cents > 0"
    ))
    result["rows_backfilled_from_cents"] = int(r.rowcount or 0)
    result["steps"].append(
        f"backfilled {result['rows_backfilled_from_cents']} rows from cents (× 10_000)"
    )

    # ── 4. Index for query patterns filtering on the new column ──────────
    try:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_bot_trades_fill_price_micros "
            "ON bot_trades(fill_price_micros)"
        ))
        result["steps"].append("index idx_bot_trades_fill_price_micros ensured")
    except Exception as exc:
        result["steps"].append(f"index create failed (non-fatal): {exc}")

    # ── 5. Counts AFTER ──────────────────────────────────────────────────
    counts_after = {}
    for label, sql in (
        ("null_micros_after",
         "SELECT COUNT(*) FROM bot_trades WHERE fill_price_micros IS NULL"),
        ("non_null_micros_after",
         "SELECT COUNT(*) FROM bot_trades WHERE fill_price_micros IS NOT NULL"),
        ("needs_alpaca_backfill",
         "SELECT COUNT(*) FROM bot_trades "
         "WHERE fill_price_micros IS NULL AND fill_price_cents = 0 "
         "AND origin = 'BROKER_FILL' AND qty > 0"),
    ):
        try:
            counts_after[label] = int(conn.execute(text(sql)).scalar() or 0)
        except Exception as exc:
            counts_after[label] = f"query_failed:{exc}"
    result["counts_after"] = counts_after
    result["rows_needing_alpaca_backfill"] = counts_after.get(
        "needs_alpaca_backfill", 0
    )

    # ── 6. Record + commit (caller's engine.begin() commits on context exit) ──
    _record(conn)

    result["migration"] = _MIGRATION_NAME
    return result
