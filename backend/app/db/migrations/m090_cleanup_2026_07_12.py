"""m090 — Cleanup: zero the m089 rounding drift + backfill m084/m085 records.

Two small cleanups from the 2026-07-12 post-deploy check:

1. m089 introduced a $0.20 rounding drift. Bump total was $13,141.10 but
   the halt actually freed $13,140.90 (crypto_quant_aggressive was
   $7,300.50, not the $7,300.60 my math assumed). Fix: shave $0.20 off
   stock_quant_day_momentum's post-bump value so capital-invariant
   returns to drift = $0.

2. m084 and m085 landed their data changes on their first boot but
   never recorded in schema_migrations. Every subsequent boot they
   re-execute (data-idempotent so no harm) and keep failing to record.
   Backfill their rows directly here — m089's success proved the new
   _gate.record() retry path works, so ordinary record() calls for
   m084/m085 SHOULD stick now, but the safer belt-and-suspenders is
   to just insert them here.

Idempotent: all three UPDATEs / INSERTs check current state first.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m090_cleanup_2026_07_12"
_BACKFILL_NAMES = [
    "m084_close_phantom_positions_2026_07_09",
    "m085_halt_scalp_meme_bleeders_2026_07_09",
]
_TRIM_BOT = "stock_quant_day_momentum"
_TRIM_TARGET_CENTS = 730_040   # $7,300.40 (was $7,300.60 → -$0.20)


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # ── 1. Trim $0.20 off stock_quant_day_momentum ────────────────────────
    row = conn.execute(text("""
        SELECT ba.id, ba.starting_capital_cents
          FROM bot_allocations ba
          JOIN bot_profiles bp ON bp.id = ba.profile_id
         WHERE ba.user_id = 1 AND bp.name = :n
         LIMIT 1
    """), {"n": _TRIM_BOT}).fetchone()
    if row:
        alloc_id = int(row[0])
        current = int(row[1] or 0)
        if current == _TRIM_TARGET_CENTS:
            actions.append({"trim": "already_at_target",
                            "bot": _TRIM_BOT, "cents": current})
        elif current > _TRIM_TARGET_CENTS:
            conn.execute(text(
                "UPDATE bot_allocations "
                "SET starting_capital_cents = :c, updated_at = :ts "
                "WHERE id = :aid"
            ), {"c": _TRIM_TARGET_CENTS, "ts": now_iso, "aid": alloc_id})
            actions.append({"trim": "applied", "bot": _TRIM_BOT,
                            "old_cents": current, "new_cents": _TRIM_TARGET_CENTS})
        else:
            actions.append({"trim": "skipped_current_below_target",
                            "bot": _TRIM_BOT, "cents": current,
                            "target": _TRIM_TARGET_CENTS})
    else:
        actions.append({"trim": "bot_not_found", "bot": _TRIM_BOT})

    # ── 2. Backfill m084 + m085 schema_migrations rows ────────────────────
    for name in _BACKFILL_NAMES:
        existing = conn.execute(text(
            "SELECT 1 FROM schema_migrations WHERE migration_name = :n"
        ), {"n": name}).fetchone()
        if existing:
            actions.append({"backfill": "already_present", "name": name})
            continue
        try:
            conn.execute(text(
                "INSERT INTO schema_migrations (migration_name) VALUES (:n) "
                "ON CONFLICT (migration_name) DO NOTHING"
            ), {"n": name})
            actions.append({"backfill": "inserted", "name": name})
        except Exception as exc:
            logger.error("[m090] backfill INSERT failed for %s: %s", name, exc)
            actions.append({"backfill": "failed", "name": name,
                            "error": str(exc)[:200]})

    logger.warning("[m090] actions=%s", actions)
    record(conn, _MIGRATION_NAME)
    return {"executed": True, "actions": actions}
