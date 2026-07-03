"""m056 — allocate 4 new quant stock bots per Brock 2026-07-02 directive.

Brock: "lets build quant stock traders swing and day traders a couple
different ones for each and then after we do that reallocate the capital
to them and then go from there."

Design:
  stock_quant_day_momentum  — 5m intraday, 19 mega-cap symbols
  stock_quant_day_meanrev   — 5m intraday, 20 large-caps
  stock_quant_swing_growth  — daily, 24 tech/AI names, 21-day hold
  stock_quant_swing_value   — daily, 30 quality/value names, 45-day hold

Each: $15k = $60k total.

## Where the capital comes from

Same self-balancing pattern m052/m053/m055 use:
  1. Reduce halted crypto_quant_scalper (paused_reason=admin_lock) $50k → $0
     (full drain — scalper hasn't traded in weeks, capital is dead weight)
  2. Reduce crypto_dca_btc_eth $30k → $20k (small trim, DCA can run smaller)
  3. Allocate 4 new bots @ $15k each = $60k
  4. Self-balance any residual via crypto_quant_aggressive

Net delta 0, $1M invariant preserved.

## Idempotency

Gated via _gate.already_ran. Safe on every boot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m056_seed_stock_quant_bots_2026_07"

_NEW_ALLOCATIONS = [
    ("stock_quant_day_momentum", 1_500_000),   # $15k
    ("stock_quant_day_meanrev",  1_500_000),   # $15k
    ("stock_quant_swing_growth", 1_500_000),   # $15k
    ("stock_quant_swing_value",  1_500_000),   # $15k
]

_HALTED_TARGETS = [
    ("crypto_quant_scalper", 0),           # $50k → $0 (halted, capital freed)
    ("crypto_dca_btc_eth",   2_000_000),   # $30k → $20k (trim 10k)
]

_INVARIANT_TARGET = 100_000_000
_WINNER = "crypto_quant_aggressive"


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    user_row = conn.execute(text("SELECT id FROM users WHERE id = 1")).fetchone()
    if not user_row:
        logger.warning("[m056] user_id=1 missing — skip")
        return {"skipped_reason": "no_fund_user", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # 1. Reduce halted / trim source bots
    for bot_name, target_cents in _HALTED_TARGETS:
        pid_row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot_name}).fetchone()
        if not pid_row:
            logger.warning("[m056] source bot %s missing — skipping", bot_name)
            continue
        pid = pid_row[0]
        alloc_row = conn.execute(text(
            "SELECT id, starting_capital_cents FROM bot_allocations "
            "WHERE profile_id = :pid AND user_id = 1"
        ), {"pid": pid}).fetchone()
        if not alloc_row:
            logger.warning("[m056] no allocation for %s — skipping", bot_name)
            continue
        alloc_id, current_cents = alloc_row
        current_cents = int(current_cents or 0)
        if current_cents == target_cents:
            actions.append({"bot": bot_name, "action": "already_target", "cents": current_cents})
            continue
        conn.execute(text(
            "UPDATE bot_allocations SET starting_capital_cents = :c, updated_at = :now "
            "WHERE id = :aid"
        ), {"c": target_cents, "now": now_iso, "aid": alloc_id})
        actions.append({
            "bot": bot_name,
            "action": "reduced",
            "from_cents": current_cents,
            "to_cents": target_cents,
            "returned_cents": current_cents - target_cents,
        })
        logger.warning(
            "[m056] %s starting_capital %d → %d (returned $%.0f)",
            bot_name, current_cents, target_cents, (current_cents - target_cents) / 100.0,
        )

    # 2. Allocate 4 new stock quant bots
    for bot_name, capital_cents in _NEW_ALLOCATIONS:
        pid_row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot_name}).fetchone()
        if not pid_row:
            logger.warning("[m056] profile %s not seeded — allocation deferred", bot_name)
            continue
        pid = pid_row[0]
        existing = conn.execute(text(
            "SELECT id FROM bot_allocations WHERE profile_id = :pid AND user_id = 1"
        ), {"pid": pid}).fetchone()
        if existing:
            actions.append({"bot": bot_name, "action": "already_allocated"})
            continue
        conn.execute(text("""
            INSERT INTO bot_allocations
                (user_id, profile_id, capital_pct, risk_profile, paper_mode,
                 go_live_requested, enabled, starting_capital_cents, tier,
                 created_at, updated_at)
            VALUES
                (1, :pid, :pct, 'aggressive', 1,
                 0, 1, :cents, 'T2', :now, :now)
        """), {
            "pid":   pid,
            "pct":   round(capital_cents / 100_000_000.0 * 100.0, 2),
            "cents": capital_cents,
            "now":   now_iso,
        })
        actions.append({"bot": bot_name, "action": "allocated", "cents": capital_cents})
        logger.warning("[m056] new bot %s allocated $%.0f", bot_name, capital_cents / 100.0)

    # 3. Self-balance via aggressive to close any residual
    winner_pid_row = conn.execute(text(
        "SELECT id FROM bot_profiles WHERE name = :n"
    ), {"n": _WINNER}).fetchone()
    if winner_pid_row:
        winner_pid = winner_pid_row[0]
        winner_alloc_row = conn.execute(text(
            "SELECT id, starting_capital_cents FROM bot_allocations "
            "WHERE profile_id = :pid AND user_id = 1"
        ), {"pid": winner_pid}).fetchone()
        if winner_alloc_row:
            winner_alloc_id, winner_current = winner_alloc_row
            winner_current = int(winner_current or 0)
            pre_sum_row = conn.execute(text(
                "SELECT COALESCE(SUM(starting_capital_cents), 0) "
                "FROM bot_allocations WHERE user_id = 1"
            )).fetchone()
            pre_sum = int(pre_sum_row[0]) if pre_sum_row else 0
            winner_new = max(0, winner_current + (_INVARIANT_TARGET - pre_sum))
            if winner_new != winner_current:
                conn.execute(text(
                    "UPDATE bot_allocations SET starting_capital_cents = :c, updated_at = :now "
                    "WHERE id = :aid"
                ), {"c": winner_new, "now": now_iso, "aid": winner_alloc_id})
                actions.append({
                    "bot": _WINNER,
                    "action": "invariant_balance",
                    "from_cents": winner_current,
                    "to_cents": winner_new,
                    "delta_cents": winner_new - winner_current,
                })
                logger.warning(
                    "[m056] %s starting_capital %d → %d (invariant delta %+d)",
                    _WINNER, winner_current, winner_new, winner_new - winner_current,
                )

    # 4. Verify invariant
    total_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    total_cents = int(total_row[0]) if total_row else 0
    invariant_ok = (total_cents == _INVARIANT_TARGET)
    logger.warning(
        "[m056] post-allocation invariant: %d cents (expected %d) ok=%s",
        total_cents, _INVARIANT_TARGET, invariant_ok,
    )
    if not invariant_ok:
        logger.critical(
            "[m056] INVARIANT BROKEN — sum=%d not $1M. Not recording gate.", total_cents,
        )
        return {"invariant_ok": False, "sum_cents": total_cents, "actions": actions}

    record(conn, _MIGRATION_NAME)
    return {
        "invariant_ok": True,
        "sum_cents": total_cents,
        "actions": actions,
        "executed": True,
    }
