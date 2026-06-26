"""m025 — Hard clean-slate to $1,000,000 with intra-sleeve rebalance for user_id=1.

Why this migration runs after m024:
  Production drifted to $3,024,365 between m024 land and 2026-06-26 (a 202% inflation
  vs the $1M canonical). Cause is the multi-aggregator divergence documented in
  context/05-known-issues.md #1. m025 is the corrective Round 2 + reallocation.

What's different from m024:
  Sleeve TOTALS are unchanged at $270K Stocks / $270K Crypto / $100K Options /
  $260K Quant / $100K Cash Floor = $1M. INTRA-sleeve allocations shift:
    - Crypto: onchain demoted from #1 ($90K) to #4 ($50K). day promoted $70K->$90K.
              swing $60K->$70K. lt $50K->$60K.
    - Quant:  aggressive promoted from #2 ($80K) to #1 ($110K). mean_reversion
              demoted from #1 ($110K) to #2 ($80K). scalper unchanged at $70K.
    - Stocks / Options / Cash Floor: unchanged from m024.

What this migration writes:
  For each of the 13 enabled bots under user_id=1:
    - starting_capital_cents := SPEC[name]
    - inception_capital_cents := SPEC[name]      (one-time corrective overwrite —
                                                  documented in spec, mirrors m024)
    - current_capital_cents  := SPEC[name] + cumulative_realized_cents
                                where cumulative_realized = SUM(bot_daily_pnl
                                .realized_cents) over rows for the canonical
                                alloc_id under user 1
  Duplicate enabled allocation rows for the same bot (m021 seed-loop residue) are
  inventoried into the cross_alloc_quarantine_m025 table with action='review'.
  Brock decides per-row. No auto-close (vault decision-history.md mass-action-restraint).

What this migration does NOT do:
  Spec from Brock called for a cash_balance_cents update of (SPEC - SUM(invested_cents))
  on open positions. bot_allocations has neither cash_balance_cents nor
  invested_cents columns. That sub-step is intentionally dropped here and surfaced
  as a follow-up.

Idempotent: schema_migrations short-circuit + absolute-set UPDATEs.
Multi-user safe: every UPDATE carries WHERE user_id = 1. Probe at end asserts zero
  other-user rows updated after migration_start_iso.
Hard-errors if any of the 13 enabled bots is missing or final sums != $1,000,000.

Safety scope note: m025 matches rows by canonical alloc_id (MIN(id) per bot under
user 1, enabled=1). This user+name predicate IS the safety scope. Not a
date-predicated quarantine migration (vault known-issues #8 applies to date-matched
opens, not capital fields).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from sqlalchemy import text

logger = logging.getLogger(__name__)

TARGET_USER_ID = 1

# Canonical allocation amounts (cents) per Brock's m025 SHIP RECAP spec.
# DO NOT import from m024 or m023 — m025 owns its source of truth.
# Brock's spec used aspirational slugs (stock_long_term, crypto_lt_dca,
# quant_mean_rev, quant_scalper); mapped here to real bot_profiles.name values.
ALLOCATIONS_CENTS: dict[str, int] = {
    # STOCKS sleeve — $270K
    "stock_swing":                  11_000_000,  # spec: stock_swing $110K
    "stock_lt":                      9_000_000,  # spec: stock_long_term $90K
    "stock_day":                     7_000_000,  # spec: stock_day $70K
    # CRYPTO sleeve — $270K (intra-sleeve rebalance vs m024)
    "crypto_day":                    9_000_000,  # was $70K in m024, now $90K
    "crypto_swing":                  7_000_000,  # was $60K in m024, now $70K
    "crypto_lt":                     6_000_000,  # spec: crypto_lt_dca $60K
    "crypto_onchain":                5_000_000,  # was $90K in m024, demoted to $50K
    # OPTIONS sleeve — $100K
    "options_income":                5_000_000,
    "options_directional":           5_000_000,
    # QUANT sleeve — $260K (intra-sleeve rebalance vs m024)
    "crypto_quant_aggressive":      11_000_000,  # was $80K in m024, promoted to $110K
    "crypto_quant_mean_reversion":   8_000_000,  # was $110K in m024, demoted to $80K
    "crypto_quant_scalper":          7_000_000,
    # CASH FLOOR — $100K
    "cash_floor":                   10_000_000,
}

# Module-level assert — catches typos before any DB is touched.
assert sum(ALLOCATIONS_CENTS.values()) == 100_000_000, (
    f"[m025] ALLOCATIONS_CENTS sum is {sum(ALLOCATIONS_CENTS.values())}, expected 100_000_000"
)

_MIGRATION_NAME = "m025_clean_slate_one_million"
_BOT_NAMES = list(ALLOCATIONS_CENTS.keys())  # 13 names

_QUARANTINE_DDL = """
CREATE TABLE IF NOT EXISTS cross_alloc_quarantine_m025 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_name TEXT NOT NULL,
    canonical_alloc_id INTEGER NOT NULL,
    duplicate_alloc_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    detected_at TEXT NOT NULL,
    action TEXT NOT NULL DEFAULT 'review',
    UNIQUE(duplicate_alloc_id)
)
"""


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
    """Idempotent hard clean-slate to $1M for user_id=1.

    Steps:
      1. Schema_migrations short-circuit.
      2. Table/column existence guards.
      3. Resolve canonical alloc_id per bot (MIN(id) per name, enabled=1, user=1).
         Hard-error if any of the 13 are missing.
      4. UPDATE starting_capital_cents, inception_capital_cents,
         current_capital_cents per spec.
      5. Inventory duplicate enabled rows into cross_alloc_quarantine_m025.
      6. Post-write read-back asserts sums == $1M.
      7. Multi-user safety probe.
      8. Record migration_name in schema_migrations.
    """
    migration_start_iso = datetime.now(timezone.utc).isoformat()

    # --- Step 1: idempotency gate ---
    if _migration_already_ran(conn, _MIGRATION_NAME):
        logger.info("[m025] already applied — skipping")
        return {"skipped_reason": "already_applied", "executed": False}

    # --- Step 2: guards ---
    if not _table_exists(conn, "bot_allocations"):
        logger.info("[m025] bot_allocations missing — skipping")
        return {"skipped_reason": "missing_table_bot_allocations", "executed": False}
    if not _table_exists(conn, "bot_profiles"):
        logger.info("[m025] bot_profiles missing — skipping")
        return {"skipped_reason": "missing_table_bot_profiles", "executed": False}
    if not _column_exists(conn, "bot_allocations", "inception_capital_cents"):
        logger.info("[m025] inception_capital_cents column missing — skipping (m023 must run first)")
        return {"skipped_reason": "missing_column_inception_capital_cents", "executed": False}
    if not _column_exists(conn, "bot_allocations", "current_capital_cents"):
        logger.info("[m025] current_capital_cents column missing — skipping (m023 must run first)")
        return {"skipped_reason": "missing_column_current_capital_cents", "executed": False}

    # --- Step 2b: create quarantine table if missing ---
    conn.execute(text(_QUARANTINE_DDL))
    conn.commit()

    # --- Step 3: resolve canonical alloc_id per bot ---
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

    if len(name_to_alloc) == 0:
        raise RuntimeError(
            "[m025] user_id=1 has 0 enabled bot_allocations — clean-slate didn't seed"
        )
    missing = [n for n in _BOT_NAMES if n not in name_to_alloc]
    if missing:
        raise RuntimeError(
            f"[m025] missing enabled allocation rows for user 1: {missing}"
        )

    # --- Step 4: UPDATE each bot to spec ---
    per_bot: list[dict] = []

    for name in _BOT_NAMES:
        alloc_id = name_to_alloc[name]
        spec_cents = ALLOCATIONS_CENTS[name]

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

    # --- Step 5: inventory duplicate enabled rows ---
    quarantined_count = 0
    for name, dup_ids in duplicate_alloc_ids.items():
        canonical_id = name_to_alloc[name]
        for dup_id in dup_ids:
            conn.execute(
                text("""
                    INSERT INTO cross_alloc_quarantine_m025
                        (bot_name, canonical_alloc_id, duplicate_alloc_id,
                         user_id, detected_at, action)
                    VALUES (:bn, :cid, :did, :uid, :ts, 'review')
                    ON CONFLICT(duplicate_alloc_id) DO NOTHING
                """),
                {
                    "bn": name,
                    "cid": canonical_id,
                    "did": dup_id,
                    "uid": TARGET_USER_ID,
                    "ts": migration_start_iso,
                },
            )
            quarantined_count += 1

    conn.commit()

    # --- Step 6: acceptance gate — read back canonical rows ---
    canonical_alloc_ids = list(name_to_alloc.values())
    id_params = {f"aid{i}": aid for i, aid in enumerate(canonical_alloc_ids)}
    id_placeholders = ", ".join(f":aid{i}" for i in range(len(canonical_alloc_ids)))

    verify_rows = conn.execute(
        text(f"""
            SELECT p.name, a.starting_capital_cents, a.inception_capital_cents
              FROM bot_allocations a
              JOIN bot_profiles p ON p.id = a.profile_id
             WHERE a.id IN ({id_placeholders})
        """),
        {**id_params},
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
                f"[m025] post-update spec mismatch: {vname} starting_capital_cents="
                f"{v_starting}, expected {expected}"
            )
        if v_inception != expected:
            raise RuntimeError(
                f"[m025] post-update spec mismatch: {vname} inception_capital_cents="
                f"{v_inception}, expected {expected}"
            )
        sum_starting += v_starting
        sum_inception += v_inception

    if sum_starting != 100_000_000:
        raise RuntimeError(
            f"[m025] post-update SUM(starting_capital_cents)={sum_starting}, expected 100_000_000"
        )
    if sum_inception != 100_000_000:
        raise RuntimeError(
            f"[m025] post-update SUM(inception_capital_cents)={sum_inception}, expected 100_000_000"
        )

    # --- Step 7: multi-user safety probe ---
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
            f"[m025] multi-user safety violation: {other_users_touched} rows outside user_id=1 "
            f"were updated at or after {migration_start_iso}"
        )

    # --- Step 8: record migration applied ---
    _record_migration(conn, _MIGRATION_NAME)

    result = {
        "executed": True,
        "user_id": TARGET_USER_ID,
        "rows_updated": 13,
        "sum_starting_cents": sum_starting,
        "sum_inception_cents": sum_inception,
        "per_bot": per_bot,
        "other_users_touched": int(other_users_touched),
        "quarantined": quarantined_count,
    }
    if duplicate_alloc_ids:
        result["duplicate_alloc_ids"] = duplicate_alloc_ids

    logger.warning(
        "[m025] executed=True · rows_updated=13 · sum_starting=%d · sum_inception=%d"
        " · other_users_touched=%d · quarantined=%d",
        sum_starting,
        sum_inception,
        int(other_users_touched),
        quarantined_count,
    )
    return result
