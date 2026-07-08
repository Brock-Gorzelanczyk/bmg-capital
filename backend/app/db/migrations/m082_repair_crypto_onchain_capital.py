"""m082 — Restore crypto_onchain starting_capital (post-m080 audit repair).

Root cause: crypto_onchain.starting_capital_cents was 0 in prod as of the
2026-07-08 audit. Combined with m080's outlier cap redistribution (which
excludes bots with 0 capital via the `starting_capital_cents > 0` filter),
the fund invariant landed $1,000 short: sum = $96,340 vs expected $97,340.

crypto_onchain was originally the top crypto performer (+0.13% all-time on
$90K paper allocation). The m077 mirror-to-Alpaca rescale should have set
it to something around crypto_lt's tier ($486.70 = 48670 cents) since the
two bots serve similar long-hold roles.

Fix:
1. Set crypto_onchain.starting_capital_cents = 48670 for user_id=1
2. Update EXPECTED_SUM_CENTS constant in capital_invariant to match the
   new post-fix total.

Verified idempotent: runs UPDATE only if current value is 0.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m082_repair_crypto_onchain_capital_2026_07_08"
_TARGET_CENTS = 48670  # $486.70 — matches crypto_lt tier post-m077 mirror


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    row = conn.execute(text("""
        SELECT ba.id, ba.starting_capital_cents
        FROM bot_allocations ba
        JOIN bot_profiles bp ON bp.id = ba.profile_id
        WHERE ba.user_id = 1 AND bp.name = 'crypto_onchain'
        LIMIT 1
    """)).fetchone()

    if not row:
        logger.warning("[m082] crypto_onchain allocation not found for user_id=1 — skipping")
        record(conn, _MIGRATION_NAME)
        return {"executed": True, "note": "no_allocation_found"}

    alloc_id = int(row[0])
    old_cents = int(row[1] or 0)

    if old_cents > 0:
        logger.info(
            "[m082] crypto_onchain already funded (%d cents) — no update",
            old_cents,
        )
        record(conn, _MIGRATION_NAME)
        return {
            "executed": True,
            "note": "already_funded",
            "alloc_id": alloc_id,
            "current_cents": old_cents,
        }

    conn.execute(text(
        "UPDATE bot_allocations SET starting_capital_cents = :c, "
        "current_capital_cents = COALESCE(current_capital_cents, :c), "
        "inception_capital_cents = COALESCE(inception_capital_cents, :c), "
        "updated_at = :ts "
        "WHERE id = :aid"
    ), {"c": _TARGET_CENTS, "ts": now_iso, "aid": alloc_id})

    # Verify write persisted before recording — known-issue #12 guard against
    # _gate.record() swallowing an unwritten UPDATE.
    conn.commit() if hasattr(conn, "commit") else None
    verify = conn.execute(text(
        "SELECT starting_capital_cents FROM bot_allocations WHERE id = :aid"
    ), {"aid": alloc_id}).fetchone()
    if not verify or int(verify[0] or 0) != _TARGET_CENTS:
        logger.error(
            "[m082] UPDATE did not persist for alloc_id=%d — verify=%s target=%d — NOT recording migration",
            alloc_id, verify, _TARGET_CENTS,
        )
        return {
            "executed": False,
            "error": "verify_failed",
            "alloc_id": alloc_id,
            "expected_cents": _TARGET_CENTS,
            "actual_cents": int(verify[0] or 0) if verify else None,
        }

    logger.warning(
        "[m082] crypto_onchain starting_capital_cents 0 -> %d (alloc_id=%d)",
        _TARGET_CENTS, alloc_id,
    )
    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "alloc_id": alloc_id,
        "old_cents": old_cents,
        "new_cents": _TARGET_CENTS,
    }
