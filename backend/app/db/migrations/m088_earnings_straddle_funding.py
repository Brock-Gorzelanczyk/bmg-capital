"""m088 — Bump options_directional allocation for earnings_straddle strategy.

earnings_straddle strategy file (backend/strategy_lab/strategies/
earnings_straddle.py) is wired into options_directional.yaml. This
migration bumps options_directional starting_capital_cents by 92020
cents ($920.20) — the remainder of the $2,920.20 pool m085 freed
after m086 ($1,000) and m087 ($1,000).

Post-migration:
  options_directional: $1,946.80 → $2,866.80 (+$920.00)
  Total fund invariant: preserved at $96,826.70.

Idempotent via _gate.record().
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m088_earnings_straddle_funding_2026_07_09"
_BUMP_CENTS = 92_020  # $920.20 — exact remainder from m085 pool


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    row = conn.execute(text("""
        SELECT ba.id, ba.starting_capital_cents
          FROM bot_allocations ba
          JOIN bot_profiles bp ON bp.id = ba.profile_id
         WHERE ba.user_id = 1 AND bp.name = 'options_directional'
         LIMIT 1
    """)).fetchone()

    if not row:
        logger.error("[m088] options_directional allocation not found — cannot bump")
        return {"executed": False, "error": "allocation_not_found"}

    alloc_id = int(row[0])
    old_cents = int(row[1] or 0)
    new_cents = old_cents + _BUMP_CENTS

    conn.execute(text(
        "UPDATE bot_allocations "
        "SET starting_capital_cents = :c, "
        "    current_capital_cents = COALESCE(current_capital_cents, 0) + :bump, "
        "    updated_at = :ts "
        "WHERE id = :aid"
    ), {"c": new_cents, "bump": _BUMP_CENTS, "ts": now_iso, "aid": alloc_id})

    if hasattr(conn, "commit"):
        conn.commit()

    verify = conn.execute(text(
        "SELECT starting_capital_cents FROM bot_allocations WHERE id = :aid"
    ), {"aid": alloc_id}).fetchone()
    if not verify or int(verify[0] or 0) != new_cents:
        logger.error(
            "[m088] verify failed: alloc_id=%d expected=%d actual=%s",
            alloc_id, new_cents, verify,
        )
        return {"executed": False, "error": "verify_failed",
                "alloc_id": alloc_id, "expected_cents": new_cents}

    logger.warning(
        "[m088] options_directional alloc_id=%d starting_capital %d → %d (+%d)",
        alloc_id, old_cents, new_cents, _BUMP_CENTS,
    )
    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "alloc_id": alloc_id,
        "old_cents": old_cents,
        "new_cents": new_cents,
        "bump_cents": _BUMP_CENTS,
    }
