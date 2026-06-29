"""m021 — Merge duplicate bot_allocations + resize to flat $200K per bot.

State going in (per audit on 2026-06-24):
  - 12 enabled bots, every one had 4-8 duplicate allocation rows
  - Total enabled "allocated" capital was ~$4.8M against a $1.42M fleet
  - Each duplicate originated from a separate _ensure_portfolios_for_user
    re-seed creating a fresh row instead of binding to existing

Plan:
  For each enabled profile:
    1. Pick lowest-id row as the canonical.
    2. UPDATE canonical: starting_capital_cents = TARGET_PER_BOT_CENTS
       (flat $200K — Brock's "way bigger evenly allocated" call).
    3. UPDATE all other duplicate rows for that profile:
       enabled = 0, paused_reason = 'merged_into_<canonical_id>'.

Idempotent — if no profile has >1 enabled row AND the canonical is already
at the target, the migration is a no-op.

Reversible — the duplicate rows stay in the table with enabled=0 +
paused_reason explaining what happened. Restoring is a SQL UPDATE.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

TARGET_PER_BOT_CENTS = 20_000_000  # $200,000
_MIGRATION_NAME = "m021_merge_and_resize_allocations_2026_06"


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
    try:
        conn.execute(
            text("INSERT INTO schema_migrations (migration_name) VALUES (:n)"
                 " ON CONFLICT (migration_name) DO NOTHING"),
            {"n": name},
        )
        conn.commit()
    except Exception as exc:
        logger.warning("[m021] _record_migration failed: %s", exc)


def run(conn) -> dict:
    # Idempotency gate (added 2026-06-28). m021 was a one-time corrective
    # migration. Without this gate it re-ran on every boot and re-overwrote
    # m027's spec amounts back to $200K, inflating the canonical sum to
    # $2.6M (13 enabled bots × $200K). See .pipeline/01-spec.md root cause.
    if _migration_already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    if not _table_exists(conn, "bot_allocations"):
        logger.info("[m021] bot_allocations missing — no-op")
        return {"skipped_reason": "table_missing"}
    if not _table_exists(conn, "bot_profiles"):
        logger.info("[m021] bot_profiles missing — no-op")
        return {"skipped_reason": "profiles_table_missing"}

    # All enabled rows grouped by (user_id, profile_id) — not just
    # profile_id. The original m021 grouped globally, which silently
    # merged one user's allocs INTO another user's lowest-id row when
    # they shared a profile. Per-user dedup preserves multi-tenant
    # separation.
    rows = conn.execute(text("""
        SELECT a.id, a.user_id, a.profile_id, a.starting_capital_cents, p.name
          FROM bot_allocations a
          JOIN bot_profiles p ON p.id = a.profile_id
         WHERE a.enabled = 1
         ORDER BY a.user_id, a.profile_id, a.id
    """)).fetchall()

    by_user_profile: dict[tuple[int, int], list] = {}
    for r in rows:
        by_user_profile.setdefault((int(r[1]), int(r[2])), []).append({
            "id": int(r[0]),
            "user_id": int(r[1]),
            "start_cents": int(r[3] or 0),
            "name": r[4],
        })

    merged_profiles = 0
    rows_demoted = 0
    rows_resized = 0
    summary: list[dict] = []

    for (user_id, profile_id), members in by_user_profile.items():
        members.sort(key=lambda m: m["id"])
        canonical = members[0]
        duplicates = members[1:]

        # No-op detection: only one row AND already at target
        if not duplicates and canonical["start_cents"] == TARGET_PER_BOT_CENTS:
            continue

        # Step 1: demote duplicates
        if duplicates:
            for d in duplicates:
                conn.execute(text("""
                    UPDATE bot_allocations
                       SET enabled = 0,
                           paused_reason = :reason
                     WHERE id = :id
                """), {
                    "reason": f"merged_into_{canonical['id']}",
                    "id": d["id"],
                })
                rows_demoted += 1
            merged_profiles += 1

        # Step 2: resize canonical to target
        if canonical["start_cents"] != TARGET_PER_BOT_CENTS:
            conn.execute(text("""
                UPDATE bot_allocations
                   SET starting_capital_cents = :cents
                 WHERE id = :id
            """), {"cents": TARGET_PER_BOT_CENTS, "id": canonical["id"]})
            rows_resized += 1

        summary.append({
            "user_id": user_id,
            "profile": canonical["name"],
            "canonical_id": canonical["id"],
            "canonical_old_cents": canonical["start_cents"],
            "canonical_new_cents": TARGET_PER_BOT_CENTS,
            "demoted_ids": [d["id"] for d in duplicates],
            "demoted_capital_cents": sum(d["start_cents"] for d in duplicates),
        })

    conn.commit()

    logger.warning(
        "[m021] merged %d profiles · demoted %d rows · resized %d canonicals to $%d",
        merged_profiles, rows_demoted, rows_resized, TARGET_PER_BOT_CENTS // 100,
    )
    _record_migration(conn, _MIGRATION_NAME)
    return {
        "merged_profiles": merged_profiles,
        "rows_demoted": rows_demoted,
        "rows_resized": rows_resized,
        "target_per_bot_cents": TARGET_PER_BOT_CENTS,
        "summary": summary,
        "executed": True,
    }
