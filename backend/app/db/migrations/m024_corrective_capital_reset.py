"""m024 — Corrective capital reset for user_id=1.

Fixes three compounded bugs from m021/m022/m023:
  (a) starting_capital_cents per-bot drifted from the spec in
      context/04-bot-fleet.md (m021 flattened to $200K, m022 partial fix).
  (b) inception_capital_cents was backfilled in m023 from a stale historical
      seed dict. Reset to match starting per-bot for the 13 enabled bots.
      From this migration forward, inception is the immutable contract.
  (c) current_capital_cents stuck at $200K for crypto_onchain,
      crypto_quant_aggressive, crypto_quant_mean_reversion, crypto_quant_scalper.
      Recomputed as starting + cumulative_realized_cents (SUM over
      bot_daily_pnl.realized_cents for the canonical alloc_id).

Simplification: open-position unrealized MTM is intentionally NOT included
in current_capital_cents. The clean-slate reset (m022 / commit 77f226a)
flushed all open positions, so unrealized at migration time is near-zero.
Including it would risk double-counting if a P&L roll-up race closes a
position between the SELECT and the UPDATE.

Idempotent: every UPDATE writes absolute values keyed by alloc_id.
Multi-user safe: every UPDATE carries WHERE user_id = 1.
Hard-errors if any of the 13 enabled bots is missing or final sums don't
equal $1,000,000.

Safety scope note: m024 matches rows by alloc_id resolved from
  enabled=1 AND user_id=1 AND profile_name IN (13 known names)
This user_id + profile_name predicate IS the safety scope. This is NOT
a date-predicated quarantine migration (the date-predicated REJECT rule
from known-issues #8 applies to migrations matching by opened_at). m024
matches by canonical alloc_id only — no date filter on the rows updated.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from sqlalchemy import text

logger = logging.getLogger(__name__)

TARGET_USER_ID = 1

# Canonical allocation amounts (cents) — source of truth for this migration.
# Mirrors backend/app/routers/clean_slate.py:59-73 (ALLOCATIONS) but is
# deliberately duplicated here so the migration owns its values and does NOT
# import a router at migration time.
# DO NOT import HISTORICAL_INCEPTION_CENTS from m023 — that dict is stale.
ALLOCATIONS_CENTS: dict[str, int] = {
    # STOCKS sleeve — $270K
    "stock_swing":                  11_000_000,
    "stock_lt":                      9_000_000,
    "stock_day":                     7_000_000,
    # CRYPTO sleeve — $270K
    "crypto_onchain":                9_000_000,
    "crypto_day":                    7_000_000,
    "crypto_swing":                  6_000_000,
    "crypto_lt":                     5_000_000,
    # OPTIONS sleeve — $100K
    "options_directional":           5_000_000,
    "options_income":                5_000_000,
    # QUANT sleeve — $260K
    "crypto_quant_mean_reversion":  11_000_000,
    "crypto_quant_aggressive":       8_000_000,
    "crypto_quant_scalper":          7_000_000,
    # CASH FLOOR sleeve — $100K
    "cash_floor":                   10_000_000,
}

# Assert at module load time — catches typos before any DB is touched.
assert sum(ALLOCATIONS_CENTS.values()) == 100_000_000, (
    f"[m024] ALLOCATIONS_CENTS sum is {sum(ALLOCATIONS_CENTS.values())}, expected 100_000_000"
)

_MIGRATION_NAME = "m024_corrective_capital_reset"
_BOT_NAMES = list(ALLOCATIONS_CENTS.keys())  # 13 names


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return bool(rows)


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return any(r[1] == column for r in rows)


def _migration_already_ran(conn, name: str) -> bool:
    try:
        result = conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_name = :n"),
            {"n": name},
        ).fetchone()
        return result is not None
    except Exception:
        return False


def _record_migration(conn, name: str) -> None:
    conn.execute(
        text(
            "INSERT INTO schema_migrations (migration_name) VALUES (:n)"
            " ON CONFLICT (migration_name) DO NOTHING"
        ),
        {"n": name},
    )
    conn.commit()


def run(conn) -> dict:
    """
    Idempotent corrective migration.
    Touches ONLY user_id=1.
    For each of the 13 spec bots:
      - starting_capital_cents := ALLOCATIONS_CENTS[name]
      - inception_capital_cents := ALLOCATIONS_CENTS[name]
      - current_capital_cents := ALLOCATIONS_CENTS[name] + cumulative_realized_cents
    where cumulative_realized_cents = SUM(bot_daily_pnl.realized_cents)
    over all rows whose allocation_id is the canonical enabled row for that bot under user 1.
    Hard-errors if any of the 13 enabled rows are missing or post-update totals
    don't equal $1,000,000 cents=100_000_000.
    """
    # Capture migration start time for multi-user safety probe BEFORE any UPDATE.
    migration_start_iso = datetime.now(timezone.utc).isoformat()

    # --- Short-circuit if already applied ---
    if _migration_already_ran(conn, _MIGRATION_NAME):
        logger.info("[m024] already applied — skipping")
        return {"skipped_reason": "already_applied", "executed": False}

    # --- Guard: required tables and columns must exist ---
    if not _table_exists(conn, "bot_allocations"):
        logger.info("[m024] bot_allocations missing — skipping")
        return {"skipped_reason": "missing_table_bot_allocations", "executed": False}
    if not _table_exists(conn, "bot_profiles"):
        logger.info("[m024] bot_profiles missing — skipping")
        return {"skipped_reason": "missing_table_bot_profiles", "executed": False}
    if not _column_exists(conn, "bot_allocations", "inception_capital_cents"):
        logger.info("[m024] inception_capital_cents column missing — skipping (m023 must run first)")
        return {"skipped_reason": "missing_column_inception_capital_cents", "executed": False}
    if not _column_exists(conn, "bot_allocations", "current_capital_cents"):
        logger.info("[m024] current_capital_cents column missing — skipping (m023 must run first)")
        return {"skipped_reason": "missing_column_current_capital_cents", "executed": False}

    # --- Step 2: Resolve canonical allocation row per bot for user 1 ---
    # Use MIN(a.id) as the canonical picker — same strategy as m021.
    # Bind names as individual parameters since SQLite doesn't support array binding.
    name_params = {f"n{i}": name for i, name in enumerate(_BOT_NAMES)}
    name_placeholders = ", ".join(f":n{i}" for i in range(len(_BOT_NAMES)))

    rows = conn.execute(
        text(f"""
            SELECT MIN(a.id) AS alloc_id, p.name,
                   GROUP_CONCAT(a.id) AS all_ids
              FROM bot_allocations a
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE a.user_id = :uid
               AND a.enabled = 1
               AND p.name IN ({name_placeholders})
             GROUP BY p.name
        """),
        {"uid": TARGET_USER_ID, **name_params},
    ).fetchall()

    # --- Step 3: Build name -> alloc_id map; hard-error on missing bots ---
    name_to_alloc: dict[str, int] = {}
    duplicate_alloc_ids: dict[str, list[int]] = {}

    for row in rows:
        alloc_id = int(row[0])
        bot_name = row[1]
        all_ids_str = row[2] or str(alloc_id)
        all_ids = [int(x) for x in all_ids_str.split(",")]
        name_to_alloc[bot_name] = alloc_id
        dupes = [x for x in all_ids if x != alloc_id]
        if dupes:
            duplicate_alloc_ids[bot_name] = dupes

    # Verify all 13 bots are present.
    if len(name_to_alloc) == 0:
        raise RuntimeError(
            "[m024] user_id=1 has 0 enabled bot_allocations — clean-slate didn't complete"
        )
    for name in _BOT_NAMES:
        if name not in name_to_alloc:
            raise RuntimeError(
                f"[m024] missing enabled allocation for user 1 bot: {name}"
            )

    # --- Steps 4-5: Update each bot; collect per-bot details ---
    per_bot: list[dict] = []

    for name in _BOT_NAMES:
        alloc_id = name_to_alloc[name]
        spec_cents = ALLOCATIONS_CENTS[name]

        # Compute cumulative realized P&L (unrealized intentionally excluded — see docstring).
        realized_row = conn.execute(
            text("""
                SELECT COALESCE(SUM(realized_cents), 0)
                  FROM bot_daily_pnl
                 WHERE allocation_id = :alloc_id
            """),
            {"alloc_id": alloc_id},
        ).fetchone()
        cumulative_realized_cents = int(realized_row[0]) if realized_row else 0

        current_cents = spec_cents + cumulative_realized_cents

        # Belt-and-suspenders: include AND user_id = :uid even though alloc_id is unique.
        conn.execute(
            text("""
                UPDATE bot_allocations
                   SET starting_capital_cents   = :spec_cents,
                       inception_capital_cents  = :spec_cents,
                       current_capital_cents    = :current_cents,
                       updated_at               = CURRENT_TIMESTAMP
                 WHERE id = :alloc_id
                   AND user_id = :uid
            """),
            {
                "spec_cents": spec_cents,
                "current_cents": current_cents,
                "alloc_id": alloc_id,
                "uid": TARGET_USER_ID,
            },
        )

        per_bot.append({
            "name": name,
            "alloc_id": alloc_id,
            "starting_cents": spec_cents,
            "inception_cents": spec_cents,
            "realized_cents": cumulative_realized_cents,
            "current_cents": current_cents,
        })

    # Step 5: Commit all updates atomically.
    conn.commit()

    # --- Step 6: Acceptance gate — read back and assert ---
    verify_rows = conn.execute(
        text(f"""
            SELECT p.name, a.starting_capital_cents, a.inception_capital_cents
              FROM bot_allocations a
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE a.user_id = :uid
               AND a.enabled = 1
               AND p.name IN ({name_placeholders})
        """),
        {"uid": TARGET_USER_ID, **name_params},
    ).fetchall()

    sum_starting = 0
    sum_inception = 0
    for vrow in verify_rows:
        vname = vrow[0]
        v_starting = int(vrow[1])
        v_inception = int(vrow[2])
        expected = ALLOCATIONS_CENTS[vname]
        if v_starting != expected:
            raise RuntimeError(
                f"[m024] post-update spec mismatch: {vname} starting_capital_cents="
                f"{v_starting}, expected {expected}"
            )
        if v_inception != expected:
            raise RuntimeError(
                f"[m024] post-update spec mismatch: {vname} inception_capital_cents="
                f"{v_inception}, expected {expected}"
            )
        sum_starting += v_starting
        sum_inception += v_inception

    if sum_starting != 100_000_000:
        raise RuntimeError(
            f"[m024] post-update SUM(starting_capital_cents)={sum_starting}, expected 100_000_000"
        )
    if sum_inception != 100_000_000:
        raise RuntimeError(
            f"[m024] post-update SUM(inception_capital_cents)={sum_inception}, expected 100_000_000"
        )

    # --- Step 7: Multi-user safety probe ---
    # Every UPDATE carried WHERE user_id = 1, so this should always be 0.
    # The migration_start_iso timestamp is captured before any UPDATE.
    other_users_touched = conn.execute(
        text("""
            SELECT COUNT(*) FROM bot_allocations
             WHERE user_id != 1
               AND updated_at >= :ts
        """),
        {"ts": migration_start_iso},
    ).fetchone()[0]

    if other_users_touched != 0:
        raise RuntimeError(
            f"[m024] multi-user safety violation: {other_users_touched} rows outside user_id=1 "
            f"were updated at or after {migration_start_iso}"
        )

    # --- Record migration as applied ---
    _record_migration(conn, _MIGRATION_NAME)

    result = {
        "executed": True,
        "user_id": TARGET_USER_ID,
        "rows_updated": 13,
        "sum_starting_cents": sum_starting,
        "sum_inception_cents": sum_inception,
        "per_bot": per_bot,
        "other_users_touched": int(other_users_touched),
    }
    if duplicate_alloc_ids:
        result["duplicate_alloc_ids"] = duplicate_alloc_ids

    logger.warning(
        "[m024] executed=True · rows_updated=13 · sum_starting=%d · sum_inception=%d"
        " · other_users_touched=%d",
        sum_starting,
        sum_inception,
        int(other_users_touched),
    )
    return result
