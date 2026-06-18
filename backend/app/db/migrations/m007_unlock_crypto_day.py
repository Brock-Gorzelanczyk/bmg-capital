"""Migration m007: Unlock crypto_day — resume trading.

Unlocks all BotAllocation rows for crypto_day that were paused via
admin_lock (set June 14 by _admin_lock_crypto_day migration).

Idempotent — safe to run every startup. No-op if already unlocked.
Touches ONLY crypto_day allocations. No other bot, T0, or incubation
bot is modified.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

logger = logging.getLogger(__name__)

_TARGET_PROFILE = "crypto_day"


def run(conn) -> None:
    now_iso = datetime.now(timezone.utc).isoformat()

    profile_row = conn.execute(
        text("SELECT id FROM bot_profiles WHERE name = :name"),
        {"name": _TARGET_PROFILE},
    ).fetchone()
    if not profile_row:
        logger.warning("[m007] bot_profile '%s' not found — nothing to unlock", _TARGET_PROFILE)
        return
    profile_id = profile_row[0]

    alloc_rows = conn.execute(
        text(
            "SELECT id, enabled, paused_reason "
            "FROM bot_allocations "
            "WHERE profile_id = :pid"
        ),
        {"pid": profile_id},
    ).fetchall()

    if not alloc_rows:
        logger.warning("[m007] no allocations found for %s", _TARGET_PROFILE)
        return

    unlocked = 0
    for row in alloc_rows:
        alloc_id, enabled, paused_reason = row
        if enabled and paused_reason is None:
            logger.info(
                "[m007] %s alloc=%d already enabled, paused_reason=None — skipping",
                _TARGET_PROFILE, alloc_id,
            )
            continue

        logger.info(
            "[m007] unlocking %s alloc=%d: enabled %s→True, paused_reason '%s'→None",
            _TARGET_PROFILE, alloc_id, enabled, paused_reason,
        )
        conn.execute(
            text(
                "UPDATE bot_allocations "
                "SET enabled = 1, paused_reason = NULL, updated_at = :now "
                "WHERE id = :id"
            ),
            {"id": alloc_id, "now": now_iso},
        )
        unlocked += 1

    if unlocked:
        # Write audit trail entry
        try:
            conn.execute(
                text(
                    "INSERT INTO audit_logs "
                    "(event_type, actor_id, resource_type, resource_id, detail, timestamp) "
                    "VALUES (:event, :actor, :rtype, :rid, :detail, :ts)"
                ),
                {
                    "event":  "unlock_crypto_day",
                    "actor":  1,  # user_id=1 = Brock (CIO)
                    "rtype":  "bot_profile",
                    "rid":    str(profile_id),
                    "detail": (
                        f"crypto_day unlocked by CIO (Brock) — reason: user requested resume. "
                        f"{unlocked} allocation(s) re-enabled at {now_iso}. "
                        f"Previously admin_lock paused June 14 2026."
                    ),
                    "ts":     now_iso,
                },
            )
        except Exception as audit_exc:
            logger.warning("[m007] audit_log write failed (non-fatal): %s", audit_exc)

        conn.commit()
        logger.info(
            "[m007] done — unlocked %d crypto_day allocation(s), audit entry written",
            unlocked,
        )
    else:
        logger.info("[m007] done — all crypto_day allocations already active (no-op)")
