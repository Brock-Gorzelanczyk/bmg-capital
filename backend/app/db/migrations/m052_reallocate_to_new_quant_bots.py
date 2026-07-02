"""m052 — reallocate capital from halted quant bots to 3 new bots.

Rationale:
  crypto_quant_aggressive is the only genuinely working bot ($778/day, 3-day
  streak). crypto_quant_mean_reversion and crypto_quant_scalper are HALTED
  (Path B decision 2026-06-30, -1.30% and -2.71% all-time). Their combined
  $150k allocation is idle — earmarked but generating $0 alpha.

  Brock directive 2026-07-01 (late-night): scale the quant approach with more
  bots, reallocate capital from halted bots, ensure they show in the app.

Reallocation:
  crypto_quant_mean_reversion: $80k → $0        (fully drained)
  crypto_quant_scalper:        $100k → $50k     (halved; $50k reserve for
                                                 possible future restart)
  crypto_quant_aggressive:     $110k → $140k    (winner reinvestment: +$30k)
  crypto_quant_alt_focus:      NEW $40k
  crypto_quant_scalp_1m:       NEW $30k
  crypto_dca_btc_eth:          NEW $30k

Net delta: -$80k -$50k +$30k +$40k +$30k +$30k = $0
$1M invariant preserved.

Note on 2026-07-02 fix: first attempt shipped with an unnecessary
`conn.commit()` inside an `engine.begin()` context, which closed the
transaction after the first UPDATE (mean_rev → $0). Removed the extra
commits (engine.begin auto-commits at block exit). Also confirmed mean_rev's
current allocation is $80k not $50k (audit was rounded), so scalper reduction
alone doesn't balance; added a +$30k boost to crypto_quant_aggressive (the
only genuinely profitable bot) to close the invariant.

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
    "crypto_quant_mean_reversion": 0,           # was $80k → $0
    "crypto_quant_scalper":        5_000_000,   # was $100k → $50k
}

# New allocations (in cents)
_NEW_ALLOCATIONS = [
    ("crypto_quant_alt_focus", 4_000_000),   # $40k
    ("crypto_quant_scalp_1m",  3_000_000),   # $30k
    ("crypto_dca_btc_eth",     3_000_000),   # $30k
]

# Winner-reinvestment via self-balancing invariant target.
# crypto_quant_aggressive is the only bot generating alpha for the 22-day
# audit window. The migration reads the pre-run sum of all user_id=1
# allocations and adjusts aggressive's capital so post-run sum equals exactly
# $1M. This survives partial prior runs (which happened on 2026-07-02 when
# earlier bugs left mean_rev at $0 and scalper at $50k with no new bots
# allocated), because it computes the correct delta from CURRENT state, not
# from a hardcoded assumption about what the audit thought each bot had.


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
                 go_live_requested, enabled, starting_capital_cents, tier,
                 created_at, updated_at)
            VALUES
                (1, :pid, :pct, 'aggressive', 1,
                 0, 1, :cents, 'T2', :now, :now)
        """), {
            "pid":   pid,
            "pct":   round(capital_cents / 100_000_000.0 * 100.0, 2),  # of $1M
            "cents": capital_cents,
            "now":   now_iso,
        })
        actions.append({
            "bot": bot_name,
            "action": "allocated",
            "cents": capital_cents,
        })
        logger.warning(
            "[m052] new bot %s allocated $%.0f (user_id=1, enabled=1, paper=1)",
            bot_name, capital_cents / 100.0,
        )

    # 3b. Self-balancing winner adjustment. Read current sum across ALL
    # user_id=1 allocations (active + halted) and compute the delta needed
    # to hit exactly $1M. Push that delta into crypto_quant_aggressive,
    # positive or negative. This is idempotent AND survives partial prior
    # runs — no matter what state the DB is in when m052 fires, the
    # aggressive allocation is set to whatever amount makes the invariant
    # close to $1M exact. Beats hardcoded deltas that drift when audit
    # snapshots turn out to be off (mean_rev was actually $80k not $50k,
    # scalper was $70k not $100k — hardcoded math would keep breaking).
    _INVARIANT_TARGET = 100_000_000  # $1M in cents
    _WINNER = "crypto_quant_aggressive"

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
            winner_alloc_id, winner_current_cents = winner_alloc_row
            winner_current_cents = int(winner_current_cents or 0)

            # Current sum across ALL user 1 allocations (including winner)
            pre_sum_row = conn.execute(text(
                "SELECT COALESCE(SUM(starting_capital_cents), 0) "
                "FROM bot_allocations WHERE user_id = 1"
            )).fetchone()
            pre_sum = int(pre_sum_row[0]) if pre_sum_row else 0

            # Winner's new cents = current + (target - pre_sum). If pre_sum
            # is already $1M this is a no-op; if it's short we boost, if
            # over we reduce. Clamp to prevent negative allocations.
            winner_new_cents = max(0, winner_current_cents + (_INVARIANT_TARGET - pre_sum))
            if winner_new_cents != winner_current_cents:
                conn.execute(text(
                    "UPDATE bot_allocations "
                    "SET starting_capital_cents = :c, updated_at = :now "
                    "WHERE id = :aid"
                ), {"c": winner_new_cents, "now": now_iso, "aid": winner_alloc_id})
                actions.append({
                    "bot": _WINNER,
                    "action": "invariant_balance",
                    "from_cents": winner_current_cents,
                    "to_cents": winner_new_cents,
                    "delta_cents": winner_new_cents - winner_current_cents,
                })
                logger.warning(
                    "[m052] winner %s starting_capital %d → %d (invariant delta %+d)",
                    _WINNER, winner_current_cents, winner_new_cents,
                    winner_new_cents - winner_current_cents,
                )
            else:
                actions.append({"bot": _WINNER, "action": "invariant_already_balanced"})

    # 4. Verify invariant. Sum across ALL user 1 allocations must == $1M.
    # Uses the same filter as the self-balance step above so the two agree.
    total_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
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
