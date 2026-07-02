"""m053 — allocate 5 new quant bot profiles per Brock 2026-07-02 directive.

Follow-up to m052's 3-bot batch. Brock: "add more quant bots now i want atleast
5 more making just as many trades as the other."

Design: 5 bots, all reuse the proven 8-strategy quant stack from Aggressive,
differentiated by universe + timeframe:

  crypto_quant_universe_top6  — top-6 majors only,     5m cadence
  crypto_quant_defi_l2        — DeFi/L2 basket,        5m cadence
  crypto_quant_meme_tier      — meme + high-beta,      5m cadence
  crypto_quant_10m            — full 20 coins,         10m cadence
  crypto_quant_15m            — full 20 coins,         15m cadence

$20k each = $100k total, funded via the same self-balancing pattern m052
uses — crypto_quant_aggressive absorbs the delta. After m052's boost put
aggressive at $190k, m053 will pull $100k back to fund the new bots, landing
aggressive at ~$90k (close to its pre-boost $110k baseline).

Idempotent via _gate. If the gate is recorded this whole migration is a
no-op; safe to re-run on every boot.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m053_seed_five_more_quant_bots_2026_07"

_NEW_ALLOCATIONS = [
    ("crypto_quant_universe_top6", 2_000_000),   # $20k
    ("crypto_quant_defi_l2",       2_000_000),   # $20k
    ("crypto_quant_meme_tier",     2_000_000),   # $20k
    ("crypto_quant_10m",           2_000_000),   # $20k
    ("crypto_quant_15m",           2_000_000),   # $20k
]

_INVARIANT_TARGET = 100_000_000  # $1M in cents
_WINNER = "crypto_quant_aggressive"


def run(conn) -> dict:
    """Allocate 5 new bots and self-balance invariant against Aggressive."""
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    user_row = conn.execute(text(
        "SELECT id FROM users WHERE id = 1"
    )).fetchone()
    if not user_row:
        logger.warning("[m053] user_id=1 not present — cannot allocate; skipping")
        return {"skipped_reason": "no_fund_user", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # 1. Allocate each of the 5 new bots (skip if profile not yet seeded)
    for bot_name, capital_cents in _NEW_ALLOCATIONS:
        pid_row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot_name}).fetchone()
        if not pid_row:
            logger.warning(
                "[m053] profile %s not seeded — allocation deferred to next boot",
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
            "pct":   round(capital_cents / 100_000_000.0 * 100.0, 2),
            "cents": capital_cents,
            "now":   now_iso,
        })
        actions.append({
            "bot": bot_name,
            "action": "allocated",
            "cents": capital_cents,
        })
        logger.warning(
            "[m053] new bot %s allocated $%.0f",
            bot_name, capital_cents / 100.0,
        )

    # 2. Self-balance: pull the delta from crypto_quant_aggressive so the
    #    invariant remains at exactly $1M. Same pattern as m052 phase 3b.
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
                    "UPDATE bot_allocations "
                    "SET starting_capital_cents = :c, updated_at = :now "
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
                    "[m053] winner %s starting_capital %d → %d (invariant delta %+d)",
                    _WINNER, winner_current, winner_new,
                    winner_new - winner_current,
                )

    # 3. Verify invariant
    total_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    total_cents = int(total_row[0]) if total_row else 0
    invariant_ok = (total_cents == _INVARIANT_TARGET)
    logger.warning(
        "[m053] post-allocation invariant: %d cents (expected %d) ok=%s",
        total_cents, _INVARIANT_TARGET, invariant_ok,
    )
    if not invariant_ok:
        logger.critical(
            "[m053] INVARIANT BROKEN — sum=%d not $1M. Not recording gate; "
            "review m053 actions before next boot.", total_cents,
        )
        return {"invariant_ok": False, "sum_cents": total_cents, "actions": actions}

    record(conn, _MIGRATION_NAME)
    return {
        "invariant_ok": True,
        "sum_cents": total_cents,
        "actions": actions,
        "executed": True,
    }
