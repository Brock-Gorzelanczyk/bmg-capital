"""m061 — Kill crypto_onchain, redirect $30K to crypto_quant_aggressive.

Diagnosed 2026-07-03: crypto_onchain fires its cron every 4h, runs all 6
strategies, but every strategy depends on external data feeds (Glassnode
mvrv/sopr/exchange_outflow, Coinglass funding/liquidation, LunarCrush
sentiment) — all 3 API keys are MISSING from Railway env. The
onchain_metrics table is empty. Every scan returns 0 signals. $30K has
been dead capital since inception.

Brock's directive (2026-07-03, following full audit): "APPROVE m061 kill
+ reallocate $30K → Quant Aggressive."

## Actions
  1. Zero starting_capital_cents on ALL crypto_onchain allocations for
     user_id=1 (may be duplicate rows like the halted bots had).
  2. Add $30,000 to crypto_quant_aggressive starting_capital
     ($100,000 → $130,000).

## Invariant
  SUM(starting_capital_cents WHERE user_id = 1) must still == $1,000,000.

## Non-gated
  This is a spec-driven reallocation matching Brock's explicit approval
  paste-ready. No env-var gate.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m061_kill_onchain_reallocate_2026_07"
_INVARIANT_TARGET = 100_000_000  # $1,000,000 exact


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # 1. Zero crypto_onchain (all rows for user_id=1)
    onchain_rows = conn.execute(text(
        "SELECT a.id, a.starting_capital_cents FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND p.name = 'crypto_onchain'"
    )).fetchall()
    total_freed = 0
    for r in onchain_rows:
        prev = int(r[1] or 0)
        if prev == 0:
            actions.append({"bot": "crypto_onchain", "alloc_id": int(r[0]), "action": "already_zero"})
            continue
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET starting_capital_cents = 0, updated_at = :now "
            "WHERE id = :aid"
        ), {"aid": int(r[0]), "now": now_iso})
        total_freed += prev
        actions.append({
            "bot": "crypto_onchain",
            "alloc_id": int(r[0]),
            "action": "zeroed",
            "prev_cents": prev,
        })
        logger.warning("[m061] crypto_onchain alloc_id=%d: %d → 0", r[0], prev)

    # 2. Add to crypto_quant_aggressive
    agg_rows = conn.execute(text(
        "SELECT a.id, a.starting_capital_cents FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1 AND p.name = 'crypto_quant_aggressive'"
    )).fetchall()

    if not agg_rows:
        logger.critical("[m061] crypto_quant_aggressive not found — cannot reallocate")
        return {"invariant_ok": False, "error": "aggressive_not_found", "actions": actions}

    # Give the full delta to the FIRST aggressive allocation to preserve
    # the single-source-of-capital pattern (matches m058's approach).
    agg_id = int(agg_rows[0][0])
    agg_prev = int(agg_rows[0][1] or 0)
    agg_new = agg_prev + total_freed
    conn.execute(text(
        "UPDATE bot_allocations "
        "SET starting_capital_cents = :c, updated_at = :now "
        "WHERE id = :aid"
    ), {"aid": agg_id, "c": agg_new, "now": now_iso})
    actions.append({
        "bot": "crypto_quant_aggressive",
        "alloc_id": agg_id,
        "action": "increased",
        "prev_cents": agg_prev,
        "new_cents": agg_new,
        "delta_cents": total_freed,
    })
    logger.warning(
        "[m061] crypto_quant_aggressive alloc_id=%d: %d → %d (+%d)",
        agg_id, agg_prev, agg_new, total_freed,
    )

    # 3. Invariant check
    total = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()[0]
    total = int(total or 0)
    invariant_ok = (total == _INVARIANT_TARGET)
    logger.warning("[m061] post-fix sum: %d cents (target %d) ok=%s",
                   total, _INVARIANT_TARGET, invariant_ok)
    if not invariant_ok:
        logger.critical("[m061] INVARIANT BROKEN — sum=%d not $1M. NOT recording gate.", total)
        return {
            "invariant_ok": False,
            "sum_cents": total,
            "actions": actions,
        }

    record(conn, _MIGRATION_NAME)
    return {
        "invariant_ok": True,
        "sum_cents": total,
        "freed_from_onchain_cents": total_freed,
        "delta_to_aggressive_cents": total_freed,
        "actions": actions,
        "executed": True,
    }
