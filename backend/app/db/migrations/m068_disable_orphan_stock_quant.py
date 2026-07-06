"""m068 — Disable the 4 orphan stock_quant bots (Option B on Bug 3).

Context: m056 autonomously seeded four stock_quant bots at $15K each. m057
was Brock's own reallocation spec which excluded them in favor of a
different lineup (stock_gap_fade / stock_orb_breakout /
stock_momentum_breakout / stock_pead). m057 zeroed their capital but
did NOT touch enabled. Result: 4 allocations sit at
starting_capital_cents=0 AND enabled=true — visible in Patrick's fleet
audit as "why are these on but broke."

## What this migration does

Sets `enabled = 0` on the 4 orphan allocations for user_id=1. Does NOT
touch:
  - starting_capital_cents (still 0, from m057)
  - bot_profiles.enabled (leaves the profile itself alive so a future
    migration can re-enable + fund without recreating the row)
  - bot_signals or bot_positions history (preserved for audit)

## Fund invariant

No capital moved. Fund total = $1,000,000 before and after.

## Rollback

To re-enable later, one UPDATE:
  UPDATE bot_allocations SET enabled = 1
    WHERE profile_id IN (SELECT id FROM bot_profiles
      WHERE name IN ('stock_quant_day_meanrev', 'stock_quant_day_momentum',
                     'stock_quant_swing_growth', 'stock_quant_swing_value'))
    AND user_id = 1;
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m068_disable_orphan_stock_quant_2026_07"

_ORPHAN_NAMES = (
    "stock_quant_day_meanrev",
    "stock_quant_day_momentum",
    "stock_quant_swing_growth",
    "stock_quant_swing_value",
)


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    for name in _ORPHAN_NAMES:
        rows = conn.execute(text(
            "SELECT a.id, a.starting_capital_cents, a.enabled "
            "FROM bot_allocations a "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE a.user_id = 1 AND p.name = :n"
        ), {"n": name}).fetchall()

        if not rows:
            actions.append({"bot": name, "action": "not_found"})
            continue

        for r in rows:
            alloc_id = int(r[0])
            starting = int(r[1] or 0)
            was_enabled = bool(r[2])
            if not was_enabled:
                actions.append({
                    "bot": name, "alloc_id": alloc_id,
                    "action": "already_disabled",
                })
                continue

            # Safety: refuse to disable if the allocation somehow has capital.
            # This should be impossible given m057, but if a follow-up migration
            # funded these bots without setting enabled=false, we do not want
            # to silently stop a funded bot without a fresh spec.
            if starting > 0:
                actions.append({
                    "bot": name, "alloc_id": alloc_id,
                    "action": "skipped_has_capital",
                    "starting_cents": starting,
                })
                logger.warning(
                    "[m068] refusing to disable %s alloc_id=%d because it has "
                    "starting_capital=%d (>$0). Investigate.",
                    name, alloc_id, starting,
                )
                continue

            conn.execute(text(
                "UPDATE bot_allocations SET enabled = 0, updated_at = :now "
                "WHERE id = :aid"
            ), {"now": now_iso, "aid": alloc_id})
            actions.append({
                "bot": name, "alloc_id": alloc_id,
                "action": "disabled",
            })
            logger.warning("[m068] disabled orphan %s alloc_id=%d", name, alloc_id)

    # Invariant sanity: fund total should still be exactly $1M.
    ba_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    ba_total = int(ba_row[0] or 0) if ba_row else 0
    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) FROM portfolio_rank_bots"
    )).fetchone()
    pr_total = int(pr_row[0] or 0) if pr_row else 0
    fund_total = ba_total + pr_total
    invariant_ok = fund_total == 100_000_000

    logger.warning(
        "[m068] invariant post-check: bot_allocations=$%d "
        "portfolio_rank_bots=$%d fund_total=$%d (target $1,000,000) invariant_ok=%s",
        ba_total // 100, pr_total // 100, fund_total // 100, invariant_ok,
    )

    if not invariant_ok:
        raise RuntimeError(
            f"m068 invariant broken: fund_total={fund_total} "
            f"delta={fund_total - 100_000_000}. All UPDATEs rolled back."
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "actions": actions,
        "fund_total_cents": fund_total,
        "invariant_ok": True,
    }
