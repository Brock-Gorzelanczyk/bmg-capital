"""m058 — Brock green-light reallocation (2026-07-02 late-night).

After the pre-open critique + Brock's green-light on aggressive paper
trading, this migration redistributes the $120K sitting in halted bots
(crypto_quant_mean_reversion $70k + crypto_quant_scalper $50k) across
5 working bots per Brock's stated preference.

Brock's directive (2026-07-02, late-night paste-ready):
  "Do NOT send $120K to just 2 bots. Spread it across ALL new stock
  bots + the crypto quant bots that need more room."

## Redistribution (exact cents)

  From:  crypto_quant_mean_reversion  $70,000 → $0
         crypto_quant_scalper         $50,000 → $0
  Total pulled:                       $120,000

  To:    stock_gap_fade               $20k → $40k  (+$20k)
         stock_orb_breakout           $20k → $40k  (+$20k)
         stock_momentum_breakout      $20k → $40k  (+$20k)
         stock_pead                   $20k → $40k  (+$20k)
         crypto_quant_scalp_1m        $10k → $20k  (+$10k)
         crypto_quant_defi_l2         $20k → $30k  (+$10k)
         crypto_quant_alt_focus       $20k → $30k  (+$10k)
         crypto_quant_universe_top6   $10k → $20k  (+$10k)
  Total added:                                     $120,000

## Invariant

  SUM(starting_capital_cents WHERE user_id = 1) must still == $1,000,000.
  Refuse to record gate if invariant broken.

## Autonomy gate

  Same env-var pattern as m057. BMG_APPROVE_M058=true on Railway to
  activate. Brock's paste-ready IS the approval, so the env var can go
  live immediately.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m058_brock_greenlight_reallocation_2026_07"
_APPROVE_ENV = "BMG_APPROVE_M058"
_INVARIANT_TARGET = 100_000_000  # $1,000,000 exact

# bot_name → target starting_capital_cents (delta from m057 shown in comments)
_TARGETS: dict[str, int] = {
    # Zeroed (dead capital returned to the pool)
    "crypto_quant_mean_reversion":  0,           # was $70k
    "crypto_quant_scalper":         0,           # was $50k
    # 4 new stock bots — doubled per Brock
    "stock_gap_fade":               4_000_000,   # $40k (was $20k, +$20k)
    "stock_orb_breakout":           4_000_000,   # $40k (was $20k, +$20k)
    "stock_momentum_breakout":      4_000_000,   # $40k (was $20k, +$20k)
    "stock_pead":                   4_000_000,   # $40k (was $20k, +$20k)
    # 4 crypto quant bots that need more room
    "crypto_quant_scalp_1m":        2_000_000,   # $20k (was $10k, +$10k)
    "crypto_quant_defi_l2":         3_000_000,   # $30k (was $20k, +$10k)
    "crypto_quant_alt_focus":       3_000_000,   # $30k (was $20k, +$10k)
    "crypto_quant_universe_top6":   2_000_000,   # $20k (was $10k, +$10k)
}


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    _approve = str(os.environ.get(_APPROVE_ENV, "")).strip().lower()
    if _approve not in ("true", "1", "yes"):
        return {
            "skipped_reason": "awaiting_approval",
            "hint": f"set {_APPROVE_ENV}=true on Railway to execute",
            "executed": False,
        }

    user_row = conn.execute(text("SELECT id FROM users WHERE id = 1")).fetchone()
    if not user_row:
        return {"skipped_reason": "no_fund_user", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    for bot_name, target_cents in _TARGETS.items():
        row = conn.execute(text(
            "SELECT a.id, a.starting_capital_cents FROM bot_allocations a "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE a.user_id = 1 AND p.name = :n"
        ), {"n": bot_name}).fetchone()
        if not row:
            actions.append({"bot": bot_name, "action": "not_found", "target_cents": target_cents})
            logger.warning("[m058] %s not found in allocations", bot_name)
            continue
        alloc_id = int(row[0])
        current_cents = int(row[1] or 0)
        if current_cents == target_cents:
            actions.append({"bot": bot_name, "action": "already_target", "cents": current_cents})
            continue
        conn.execute(text(
            "UPDATE bot_allocations SET starting_capital_cents = :c, updated_at = :now "
            "WHERE id = :aid"
        ), {"c": target_cents, "now": now_iso, "aid": alloc_id})
        actions.append({
            "bot": bot_name,
            "action": "reallocated",
            "from_cents": current_cents,
            "to_cents": target_cents,
            "delta_cents": target_cents - current_cents,
        })
        logger.warning(
            "[m058] %s starting_capital %d → %d (delta %+d)",
            bot_name, current_cents, target_cents, target_cents - current_cents,
        )

    # Verify $1M invariant (count ALL user_1 allocations, not just enabled —
    # zeroed bots stay enabled=False but their $0 doesn't hurt the sum).
    total_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    total_cents = int(total_row[0]) if total_row else 0
    invariant_ok = (total_cents == _INVARIANT_TARGET)
    logger.warning(
        "[m058] post-reallocation sum: %d cents (target %d) ok=%s",
        total_cents, _INVARIANT_TARGET, invariant_ok,
    )
    if not invariant_ok:
        logger.critical(
            "[m058] INVARIANT BROKEN — sum=%d not $%d. Not recording gate.",
            total_cents, _INVARIANT_TARGET // 100,
        )
        return {
            "invariant_ok": False,
            "sum_cents": total_cents,
            "target_cents": _INVARIANT_TARGET,
            "actions": actions,
        }

    record(conn, _MIGRATION_NAME)
    return {
        "invariant_ok": True,
        "sum_cents": total_cents,
        "actions_count": len(actions),
        "executed": True,
    }
