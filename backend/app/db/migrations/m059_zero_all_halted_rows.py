"""m059 — Zero ALL bot_allocation rows for the halted bots.

Diagnosed via /api/admin/pv-breakdown-diagnostic (2026-07-03 01:XX CT):
  crypto_quant_mean_reversion: $110,000 starting_capital (should be $0)
  crypto_quant_scalper:         $70,000 starting_capital (should be $0)
  → $180,000 phantom in fleet PV vs $1M invariant

Root cause: m058 used `.fetchone()` and only updated the FIRST row per
profile. Both bots have duplicate bot_allocation rows for user_id=1
(residue from earlier clean-slate cycles). The second row for each
retained the pre-halt capital.

This migration issues a bulk UPDATE that hits ALL rows for the halted
bots, not just the first. Idempotent (already zero rows are no-ops).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m059_zero_all_halted_rows_2026_07"
_HALTED_BOTS = ("crypto_quant_mean_reversion", "crypto_quant_scalper")


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    # Snapshot pre-state per row (so we can log it and audit later).
    rows = conn.execute(text(
        "SELECT a.id, p.name, a.starting_capital_cents "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND p.name IN ('crypto_quant_mean_reversion', 'crypto_quant_scalper')"
    )).fetchall()

    zeroed = []
    for r in rows:
        alloc_id = int(r[0])
        bot_name = r[1]
        prev_cents = int(r[2] or 0)
        if prev_cents == 0:
            zeroed.append({"alloc_id": alloc_id, "bot": bot_name, "action": "already_zero"})
            continue
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET starting_capital_cents = 0, updated_at = :now "
            "WHERE id = :aid"
        ), {"aid": alloc_id, "now": now_iso})
        zeroed.append({
            "alloc_id": alloc_id,
            "bot": bot_name,
            "action": "zeroed",
            "prev_cents": prev_cents,
        })
        logger.warning("[m059] zeroed alloc_id=%d bot=%s prev=%d → 0",
                       alloc_id, bot_name, prev_cents)

    # Verify invariant post-fix: SUM(starting_capital_cents WHERE user_id=1) == $1M
    total = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()[0]
    total = int(total or 0)
    invariant_ok = (total == 100_000_000)
    logger.warning("[m059] post-fix sum: %d cents (target 100000000) ok=%s",
                   total, invariant_ok)
    if not invariant_ok:
        logger.critical("[m059] INVARIANT BROKEN — sum=%d not $1,000,000. NOT recording gate.", total)
        return {
            "invariant_ok": False,
            "sum_cents": total,
            "actions": zeroed,
        }

    record(conn, _MIGRATION_NAME)
    return {
        "invariant_ok": True,
        "sum_cents": total,
        "row_actions": zeroed,
        "executed": True,
    }
