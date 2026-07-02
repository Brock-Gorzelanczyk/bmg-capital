"""m052 — reallocate capital from halted quant bots to 3 new bots.

Rationale:
  crypto_quant_aggressive is the only genuinely working bot ($778/day, 3-day
  streak). crypto_quant_mean_reversion and crypto_quant_scalper are HALTED
  (Path B decision 2026-06-30, -1.30% and -2.71% all-time). Their combined
  $150k allocation is idle — earmarked but generating $0 alpha.

  Brock directive 2026-07-01 (late-night): scale the quant approach with more
  bots, reallocate capital from halted bots, ensure they show in the app.

Reallocation:
  crypto_quant_mean_reversion: $50k → $0        (fully returned to pool)
  crypto_quant_scalper:        $100k → $50k     (halved; keep $50k reserve
                                                 for possible future restart)
  crypto_quant_alt_focus:      NEW $40k
  crypto_quant_scalp_1m:       NEW $30k
  crypto_dca_btc_eth:          NEW $30k

Net delta: -$50k -$50k +$40k +$30k +$30k = $0 → $1M invariant preserved.

The new bots' YAML files ship in this same commit; seed_bot_profiles() runs
before this migration on every boot and creates their BotProfile rows. This
migration then creates BotAllocation rows for user_id=1 and mutates the
halted bots' starting_capital_cents.

Idempotent via _gate — if the migration name shows in migration_log this
whole thing skips. Safe to run on every boot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m052_reallocate_to_new_quant_bots_2026_07"

# Halted → return-to-pool amounts (in cents)
_HALTED_TARGETS = {
    "crypto_quant_mean_reversion": 0,           # $50k → $0
    "crypto_quant_scalper":        5_000_000,   # $100k → $50k
}

# New allocations (in cents)
_NEW_ALLOCATIONS = [
    ("crypto_quant_alt_focus", 4_000_000),   # $40k
    ("crypto_quant_scalp_1m",  3_000_000),   # $30k
    ("crypto_dca_btc_eth",     3_000_000),   # $30k
]


def run(conn) -> dict:
    """Reallocate capital. Safe to run on every boot; gated by migration_log."""
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    # 1. Confirm user_id=1 exists (Brock's fund account)
    user_row = conn.execute(text(
        "SELECT id FROM users WHERE id = 1"
    )).fetchone()
    if not user_row:
        logger.warning("[m052] user_id=1 not present — cannot allocate; skipping")
        return {"skipped_reason": "no_fund_user", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # 2. Reduce halted-bot capital. Only touches user_id=1's allocation.
    for bot_name, target_cents in _HALTED_TARGETS.items():
        pid_row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot_name}).fetchone()
        if not pid_row:
            logger.warning("[m052] halted bot profile %s missing — skipping reduce", bot_name)
            continue
        pid = pid_row[0]
        alloc_row = conn.execute(text(
            "SELECT id, starting_capital_cents FROM bot_allocations "
            "WHERE profile_id = :pid AND user_id = 1"
        ), {"pid": pid}).fetchone()
        if not alloc_row:
            logger.warning("[m052] no allocation for halted %s at user_id=1 — skipping", bot_name)
            continue
        alloc_id, current_cents = alloc_row
        current_cents = int(current_cents or 0)
        if current_cents == target_cents:
            actions.append({"bot": bot_name, "action": "already_target", "cents": current_cents})
            continue
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET starting_capital_cents = :c, updated_at = :now "
            "WHERE id = :aid"
        ), {"c": target_cents, "now": now_iso, "aid": alloc_id})
        conn.commit()
        actions.append({
            "bot": bot_name,
            "action": "reduced",
            "from_cents": current_cents,
            "to_cents": target_cents,
            "returned_cents": current_cents - target_cents,
        })
        logger.warning(
            "[m052] halted %s starting_capital %d → %d (returned $%.0f to pool)",
            bot_name, current_cents, target_cents, (current_cents - target_cents) / 100.0,
        )

    # 3. Allocate to new bots. Requires seed_bot_profiles to have run first
    #    (which happens in lifespan before this migration).
    for bot_name, capital_cents in _NEW_ALLOCATIONS:
        pid_row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot_name}).fetchone()
        if not pid_row:
            logger.warning(
                "[m052] new bot profile %s not seeded yet — allocation deferred to next boot",
                bot_name,
            )
            continue
        pid = pid_row[0]
        existing = conn.execute(text(
            "SELECT id, starting_capital_cents FROM bot_allocations "
            "WHERE profile_id = :pid AND user_id = 1"
        ), {"pid": pid}).fetchone()
        if existing:
            actions.append({"bot": bot_name, "action": "already_allocated"})
            continue
        conn.execute(text("""
            INSERT INTO bot_allocations
                (user_id, profile_id, capital_pct, risk_profile, paper_mode,
                 enabled, starting_capital_cents, tier, created_at, updated_at)
            VALUES
                (1, :pid, :pct, 'aggressive', 1,
                 1, :cents, 'T2', :now, :now)
        """), {
            "pid":   pid,
            "pct":   round(capital_cents / 100_000_000.0 * 100.0, 2),  # of $1M
            "cents": capital_cents,
            "now":   now_iso,
        })
        conn.commit()
        actions.append({
            "bot": bot_name,
            "action": "allocated",
            "cents": capital_cents,
        })
        logger.warning(
            "[m052] new bot %s allocated $%.0f (user_id=1, enabled=1, paper=1)",
            bot_name, capital_cents / 100.0,
        )

    # 4. Verify invariant. Sum across active+halted must == $1M.
    total_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations "
        "WHERE user_id = 1 AND (enabled = 1 OR paused_reason IS NOT NULL)"
    )).fetchone()
    total_cents = int(total_row[0]) if total_row else 0
    invariant_ok = (total_cents == 100_000_000)
    logger.warning(
        "[m052] post-reallocation invariant: %d cents (expected 100000000) ok=%s",
        total_cents, invariant_ok,
    )

    if not invariant_ok:
        # Don't record the gate — leave the door open for a manual fix on
        # next boot rather than silently accepting a broken invariant.
        logger.critical(
            "[m052] INVARIANT BROKEN — sum=%d not $1M. Not recording gate; "
            "review m052 actions before next boot.", total_cents,
        )
        return {"invariant_ok": False, "sum_cents": total_cents, "actions": actions}

    record(conn, _MIGRATION_NAME)
    return {
        "invariant_ok": True,
        "sum_cents": total_cents,
        "actions": actions,
        "executed": True,
    }
