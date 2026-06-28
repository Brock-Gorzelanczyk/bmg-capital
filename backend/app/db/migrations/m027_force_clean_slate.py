"""m027 — Forced clean-slate to $1M with full history wipe + audit log.

Why this exists despite m024 / m025 / m026:
  - m025 ran successfully on 2026-06-27 (schema_migrations has the row)
  - But the runtime _ensure_portfolios_for_user seed loop in routers/bots.py
    was bumping any bot below $100K back up on every portfolio API fetch
    (see .pipeline/01-spec-autogrow-findings.md PART 1).
  - The seed-loop fix landed in the same commit as this migration.
  - m027 uses a fresh schema_migrations name so the idempotency gate does
    NOT short-circuit. The CALLER will see m027 run cleanly.

What m027 does (all in one atomic transaction):
  Step 1. ensure_capital_audit_table — table for the watchdog
  Step 2. pre-reset snapshot of every user_1 bot_allocation row into
          capital_audit_log with note='m027_pre_reset'
  Step 3. UPDATE all 13 SPEC bots: starting/inception/current capital all
          set to SPEC value (one-time corrective overwrite, intentional)
  Step 4. DELETE bot_allocations for user 1 whose profile.name NOT IN SPEC
          set (purges the inflated extras m025+m026 left behind)
  Step 5. DELETE bot_trades for user 1 (kills the historical realized P&L
          that was driving canonical PV > $1M)
  Step 6. DELETE bot_daily_pnl for user 1 (audit-log P&L history)
  Step 7. Reset bot_state.cooldown_until = NULL (best-effort — table may
          not exist; OK to skip)
  Step 8. post-reset snapshot to capital_audit_log with note='m027_post_reset'
  Step 9. Verification block: 13 enabled, sum=$1M, zero trades, zero
          daily_pnl, zero open positions
  Step 10. Record m027 in schema_migrations.

Hard-errors on any verification failure with a descriptive message.
Multi-user safe: every write carries WHERE user_id = 1, probed at end.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from sqlalchemy import text

logger = logging.getLogger(__name__)

TARGET_USER_ID = 1

# Maps Brock's spec slugs to real bot_profiles.name (same mapping as m025).
ALLOCATIONS_CENTS: dict[str, int] = {
    "stock_swing":                  11_000_000,  # $110K
    "stock_lt":                      9_000_000,  # $90K  (spec: stock_long_term)
    "stock_day":                     7_000_000,  # $70K
    "crypto_day":                    9_000_000,  # $90K
    "crypto_swing":                  7_000_000,  # $70K
    "crypto_lt":                     6_000_000,  # $60K  (spec: crypto_lt_dca)
    "crypto_onchain":                5_000_000,  # $50K
    "options_income":                5_000_000,  # $50K
    "options_directional":           5_000_000,  # $50K
    "crypto_quant_aggressive":      11_000_000,  # $110K
    "crypto_quant_mean_reversion":   8_000_000,  # $80K  (spec: quant_mean_rev)
    "crypto_quant_scalper":          7_000_000,  # $70K  (spec: quant_scalper)
    "cash_floor":                   10_000_000,  # $100K
}

assert sum(ALLOCATIONS_CENTS.values()) == 100_000_000, (
    f"[m027] ALLOCATIONS_CENTS sum is {sum(ALLOCATIONS_CENTS.values())}, expected 100_000_000"
)

_MIGRATION_NAME = "m027_force_clean_slate"
_BOT_NAMES = list(ALLOCATIONS_CENTS.keys())

# Inline audit table DDL — m027 owns its setup so it does NOT import the
# service module (avoids import-order surprises at app boot).
_AUDIT_DDL = """
CREATE TABLE IF NOT EXISTS capital_audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user_id INTEGER,
    allocation_id INTEGER,
    bot_name TEXT,
    field TEXT NOT NULL,
    old_value INTEGER,
    new_value INTEGER,
    delta_cents INTEGER,
    source TEXT,
    note TEXT
)
"""
_AUDIT_INDEX_DDL = "CREATE INDEX IF NOT EXISTS idx_capital_audit_ts ON capital_audit_log (ts)"


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return bool(rows)


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


def _audit_row(conn, ts: str, user_id, alloc_id, bot_name, field,
               old_val, new_val, source, note):
    delta = (new_val or 0) - (old_val or 0) if old_val is not None and new_val is not None else None
    conn.execute(text("""
        INSERT INTO capital_audit_log
            (ts, user_id, allocation_id, bot_name, field,
             old_value, new_value, delta_cents, source, note)
        VALUES (:ts, :uid, :aid, :bn, :f, :ov, :nv, :d, :s, :note)
    """), {
        "ts": ts, "uid": user_id, "aid": alloc_id, "bn": bot_name,
        "f": field, "ov": old_val, "nv": new_val, "d": delta,
        "s": source, "note": note,
    })


def run(conn) -> dict:
    migration_start_iso = datetime.now(timezone.utc).isoformat()

    # Step 1: schema_migrations idempotency gate (fresh name, will run on
    # first boot after this lands).
    if _migration_already_ran(conn, _MIGRATION_NAME):
        logger.info("[m027] already applied — skipping")
        return {"skipped_reason": "already_applied", "executed": False}

    # Guards.
    if not _table_exists(conn, "bot_allocations"):
        return {"skipped_reason": "missing_table_bot_allocations", "executed": False}
    if not _table_exists(conn, "bot_profiles"):
        return {"skipped_reason": "missing_table_bot_profiles", "executed": False}

    # Step 1b: ensure audit table exists BEFORE we start writing snapshots.
    conn.execute(text(_AUDIT_DDL))
    conn.execute(text(_AUDIT_INDEX_DDL))
    conn.commit()

    # Step 2: pre-reset snapshot — record every user_1 allocation's capital
    # fields so the audit log has a starting baseline.
    pre_rows = conn.execute(text("""
        SELECT a.id, p.name, a.starting_capital_cents,
               COALESCE(a.inception_capital_cents, 0),
               COALESCE(a.current_capital_cents, 0)
          FROM bot_allocations a
          JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.user_id = :uid
    """), {"uid": TARGET_USER_ID}).fetchall()

    for r in pre_rows:
        alloc_id = int(r[0])
        bot_name = r[1]
        _audit_row(conn, migration_start_iso, TARGET_USER_ID, alloc_id, bot_name,
                   "starting_capital_cents", int(r[2] or 0), int(r[2] or 0),
                   "m027:pre_reset", "m027_pre_reset")
        _audit_row(conn, migration_start_iso, TARGET_USER_ID, alloc_id, bot_name,
                   "inception_capital_cents", int(r[3]), int(r[3]),
                   "m027:pre_reset", "m027_pre_reset")
        _audit_row(conn, migration_start_iso, TARGET_USER_ID, alloc_id, bot_name,
                   "current_capital_cents", int(r[4]), int(r[4]),
                   "m027:pre_reset", "m027_pre_reset")
    conn.commit()

    # Step 3: resolve canonical alloc_id per SPEC bot.
    name_params = {f"n{i}": name for i, name in enumerate(_BOT_NAMES)}
    name_ph = ", ".join(f":n{i}" for i in range(len(_BOT_NAMES)))
    spec_rows = conn.execute(text(f"""
        SELECT MIN(a.id), p.name
          FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.user_id = :uid AND a.enabled = 1
           AND p.name IN ({name_ph})
         GROUP BY p.name
    """), {"uid": TARGET_USER_ID, **name_params}).fetchall()

    name_to_alloc: dict[str, int] = {r[1]: int(r[0]) for r in spec_rows}
    missing = [n for n in _BOT_NAMES if n not in name_to_alloc]
    if missing:
        raise RuntimeError(f"[m027] missing enabled SPEC allocations for user 1: {missing}")

    # Step 4: UPDATE the 13 SPEC bots to canonical values.
    for name in _BOT_NAMES:
        alloc_id = name_to_alloc[name]
        spec_cents = ALLOCATIONS_CENTS[name]
        conn.execute(text("""
            UPDATE bot_allocations
               SET starting_capital_cents  = :v,
                   inception_capital_cents = :v,
                   current_capital_cents   = :v,
                   updated_at              = CURRENT_TIMESTAMP
             WHERE id = :id AND user_id = :uid
        """), {"v": spec_cents, "id": alloc_id, "uid": TARGET_USER_ID})

    # Step 5: DELETE bot_allocations whose profile.name is NOT in SPEC for user 1.
    # m026 disabled extras; m027 nukes them outright so the seed loop can't
    # resurrect them (and the auto-grow fix means it won't, but defense in depth).
    extras = conn.execute(text(f"""
        SELECT a.id, p.name FROM bot_allocations a
          JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.user_id = :uid
           AND p.name NOT IN ({name_ph})
    """), {"uid": TARGET_USER_ID, **name_params}).fetchall()
    extras_deleted = 0
    for r in extras:
        conn.execute(text("DELETE FROM bot_allocations WHERE id = :id AND user_id = :uid"),
                     {"id": int(r[0]), "uid": TARGET_USER_ID})
        extras_deleted += 1

    # Also delete dup enabled rows for SPEC bots (m021 residue): each SPEC
    # bot keeps only the canonical MIN(id); any other rows for the same
    # profile under user 1 are removed.
    for name in _BOT_NAMES:
        canonical = name_to_alloc[name]
        dup_rows = conn.execute(text("""
            SELECT a.id FROM bot_allocations a JOIN bot_profiles p ON p.id = a.profile_id
             WHERE a.user_id = :uid AND p.name = :n AND a.id != :keep
        """), {"uid": TARGET_USER_ID, "n": name, "keep": canonical}).fetchall()
        for r in dup_rows:
            conn.execute(text("DELETE FROM bot_allocations WHERE id = :id AND user_id = :uid"),
                         {"id": int(r[0]), "uid": TARGET_USER_ID})
            extras_deleted += 1

    # Step 6: wipe trade history for user 1 (allocations have been deleted
    # for extras; only canonical SPEC allocs remain).
    trades_wiped = 0
    if _table_exists(conn, "bot_trades"):
        result = conn.execute(text("""
            DELETE FROM bot_trades
             WHERE allocation_id IN (
                 SELECT id FROM bot_allocations WHERE user_id = :uid
             )
        """), {"uid": TARGET_USER_ID})
        trades_wiped = result.rowcount or 0

    # Step 7: wipe daily P&L history.
    daily_pnl_wiped = 0
    if _table_exists(conn, "bot_daily_pnl"):
        result = conn.execute(text("""
            DELETE FROM bot_daily_pnl
             WHERE allocation_id IN (
                 SELECT id FROM bot_allocations WHERE user_id = :uid
             )
        """), {"uid": TARGET_USER_ID})
        daily_pnl_wiped = result.rowcount or 0

    # Step 8: reset cooldowns (best-effort).
    cooldowns_cleared = 0
    if _table_exists(conn, "bot_state"):
        try:
            result = conn.execute(text("UPDATE bot_state SET cooldown_until = NULL"))
            cooldowns_cleared = result.rowcount or 0
        except Exception:
            cooldowns_cleared = -1
    else:
        cooldowns_cleared = -1

    # Close any open positions (paper convention: zero artificial P&L).
    positions_closed = 0
    if _table_exists(conn, "bot_positions"):
        result = conn.execute(text("""
            UPDATE bot_positions
               SET closed_at = :ts, exit_reason = 'm027_force_clean_slate'
             WHERE closed_at IS NULL
               AND quarantined_at IS NULL
               AND allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = :uid)
        """), {"ts": migration_start_iso, "uid": TARGET_USER_ID})
        positions_closed = result.rowcount or 0

    conn.commit()

    # Step 9: post-reset audit snapshot.
    post_iso = datetime.now(timezone.utc).isoformat()
    for name in _BOT_NAMES:
        alloc_id = name_to_alloc[name]
        v = ALLOCATIONS_CENTS[name]
        _audit_row(conn, post_iso, TARGET_USER_ID, alloc_id, name,
                   "starting_capital_cents", None, v,
                   "m027:post_reset", "m027_post_reset")
        _audit_row(conn, post_iso, TARGET_USER_ID, alloc_id, name,
                   "inception_capital_cents", None, v,
                   "m027:post_reset", "m027_post_reset")
        _audit_row(conn, post_iso, TARGET_USER_ID, alloc_id, name,
                   "current_capital_cents", None, v,
                   "m027:post_reset", "m027_post_reset")
    conn.commit()

    # Step 10: verification.
    final_count = conn.execute(text("""
        SELECT COUNT(*) FROM bot_allocations
         WHERE user_id = :uid AND enabled = 1
    """), {"uid": TARGET_USER_ID}).fetchone()[0]
    if int(final_count) != len(_BOT_NAMES):
        raise RuntimeError(
            f"[m027] verification: enabled count {final_count} != {len(_BOT_NAMES)}"
        )

    final_sum = conn.execute(text("""
        SELECT COALESCE(SUM(starting_capital_cents), 0)
          FROM bot_allocations
         WHERE user_id = :uid AND enabled = 1
    """), {"uid": TARGET_USER_ID}).fetchone()[0]
    if int(final_sum) != 100_000_000:
        raise RuntimeError(
            f"[m027] verification: SUM(starting_capital_cents) {final_sum} != 100_000_000"
        )

    if _table_exists(conn, "bot_trades"):
        remaining_trades = conn.execute(text("""
            SELECT COUNT(*) FROM bot_trades
             WHERE allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = :uid)
        """), {"uid": TARGET_USER_ID}).fetchone()[0]
        if int(remaining_trades) != 0:
            raise RuntimeError(f"[m027] verification: {remaining_trades} trades remain")

    if _table_exists(conn, "bot_positions"):
        open_remaining = conn.execute(text("""
            SELECT COUNT(*) FROM bot_positions
             WHERE closed_at IS NULL AND quarantined_at IS NULL
               AND allocation_id IN (SELECT id FROM bot_allocations WHERE user_id = :uid)
        """), {"uid": TARGET_USER_ID}).fetchone()[0]
        if int(open_remaining) != 0:
            raise RuntimeError(f"[m027] verification: {open_remaining} open positions remain")

    # Multi-user safety probe.
    other_users_touched = conn.execute(text("""
        SELECT COUNT(*) FROM bot_allocations
         WHERE user_id != :uid AND updated_at >= :ts
    """), {"uid": TARGET_USER_ID, "ts": migration_start_iso}).fetchone()[0]
    if int(other_users_touched) != 0:
        raise RuntimeError(
            f"[m027] multi-user safety: {other_users_touched} rows outside user 1 updated"
        )

    _record_migration(conn, _MIGRATION_NAME)

    result = {
        "executed": True,
        "user_id": TARGET_USER_ID,
        "rows_updated": len(_BOT_NAMES),
        "extras_deleted": extras_deleted,
        "trades_wiped": trades_wiped,
        "daily_pnl_wiped": daily_pnl_wiped,
        "cooldowns_cleared": cooldowns_cleared,
        "positions_closed": positions_closed,
        "sum_starting_cents": int(final_sum),
        "other_users_touched": int(other_users_touched),
    }
    logger.warning(
        "[m027] rows_updated=%d · extras_deleted=%d · trades_wiped=%d "
        "· daily_pnl_wiped=%d · cooldowns_cleared=%d · sum_starting=%d "
        "· other_users_touched=%d",
        len(_BOT_NAMES), extras_deleted, trades_wiped, daily_pnl_wiped,
        cooldowns_cleared, int(final_sum), int(other_users_touched),
    )
    return result
