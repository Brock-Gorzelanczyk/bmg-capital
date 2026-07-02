"""m054 — restore crypto_quant_aggressive capital by draining idle cash_floor.

## Why this is needed

m053's self-balancer had to absorb the full $100k of 5 new-bot allocations
into crypto_quant_aggressive because pre-m053 sum was already $1M exactly
(m052 balanced correctly). Result: aggressive got pulled from $110k → $10k.

That's the opposite of what we want. crypto_quant_aggressive is the ONLY
bot with a 22-day profitable track record ($778/day, +2.15%). Starving it
to fund untested new bots contradicts the "reinvest in winners" directive.

## What this does

  cash_floor:              $100k → $10k     (drops $90k; cash_floor bot
                                             requires CAPITAL_EXECUTE_ENABLED
                                             env var to trade — Brock hasn't
                                             set it, so it's idle $0 alpha)
  crypto_quant_aggressive: $10k  → $100k    (+$90k, restores it near baseline)

Net delta: $0 → $1M invariant preserved.

If Brock later decides to enable cash_floor by setting the env var, we can
reverse this in another migration (m055 or ad-hoc). For now, having capital
sit idle on a config-gap bot while our proven earner starves is strictly
worse than the swap.

## Idempotency

Gated via _gate. If already applied, no-op. Safe to re-run on boot.
Additionally verifies the winner is currently at low-capital before firing —
if a manual reallocation has already restored aggressive, we don't want to
double-drain cash_floor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m054_restore_aggressive_from_cash_floor_2026_07"

_FROM_BOT = "cash_floor"
_FROM_KEEP_CENTS = 1_000_000       # keep $10k
_TO_BOT = "crypto_quant_aggressive"
_TO_TARGET_CENTS = 10_000_000      # boost to $100k
_MIN_CURRENT_TRIGGER = 5_000_000   # only run if winner has < $50k currently


def run(conn) -> dict:
    """Move $90k from cash_floor → aggressive if aggressive is starved."""
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()

    # Read both allocations for user_id=1
    def _get_alloc(bot: str) -> tuple[int | None, int]:
        pid_row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot}).fetchone()
        if not pid_row:
            return None, 0
        pid = pid_row[0]
        alloc_row = conn.execute(text(
            "SELECT id, starting_capital_cents FROM bot_allocations "
            "WHERE profile_id = :pid AND user_id = 1"
        ), {"pid": pid}).fetchone()
        if not alloc_row:
            return None, 0
        return int(alloc_row[0]), int(alloc_row[1] or 0)

    from_alloc_id, from_current = _get_alloc(_FROM_BOT)
    to_alloc_id, to_current = _get_alloc(_TO_BOT)

    if not from_alloc_id or not to_alloc_id:
        logger.warning(
            "[m054] required allocation missing (from=%s, to=%s) — skipping",
            from_alloc_id, to_alloc_id,
        )
        return {"skipped_reason": "missing_allocations", "executed": False}

    # Safety: only fire if aggressive is genuinely starved. If someone
    # already restored it, don't drain cash_floor again.
    if to_current >= _MIN_CURRENT_TRIGGER:
        logger.info(
            "[m054] winner already at %d cents (>= trigger %d) — skipping",
            to_current, _MIN_CURRENT_TRIGGER,
        )
        record(conn, _MIGRATION_NAME)  # record so we don't re-check every boot
        return {"skipped_reason": "winner_already_restored", "executed": False}

    # Move the delta. Reduce cash_floor to keep floor, boost aggressive to target.
    from_new = _FROM_KEEP_CENTS
    to_new = _TO_TARGET_CENTS
    from_delta = from_new - from_current   # negative (reducing)
    to_delta = to_new - to_current         # positive (boosting)

    # Sanity: the two deltas should sum to zero for invariant preservation.
    # If cash_floor doesn't have enough, clamp the aggressive boost.
    if abs(from_delta) < to_delta:
        logger.warning(
            "[m054] cash_floor only has $%.0f headroom, clamping aggressive boost",
            (from_current - _FROM_KEEP_CENTS) / 100.0,
        )
        to_new = to_current + abs(from_delta)

    conn.execute(text(
        "UPDATE bot_allocations SET starting_capital_cents = :c, updated_at = :now "
        "WHERE id = :aid"
    ), {"c": from_new, "now": now_iso, "aid": from_alloc_id})
    logger.warning(
        "[m054] %s starting_capital %d → %d (drained $%.0f)",
        _FROM_BOT, from_current, from_new, (from_current - from_new) / 100.0,
    )

    conn.execute(text(
        "UPDATE bot_allocations SET starting_capital_cents = :c, updated_at = :now "
        "WHERE id = :aid"
    ), {"c": to_new, "now": now_iso, "aid": to_alloc_id})
    logger.warning(
        "[m054] %s starting_capital %d → %d (boosted $%.0f)",
        _TO_BOT, to_current, to_new, (to_new - to_current) / 100.0,
    )

    # Verify invariant. Same query used by m052 / m053 / capital_invariant audit.
    total_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    total_cents = int(total_row[0]) if total_row else 0
    invariant_ok = (total_cents == 100_000_000)
    logger.warning(
        "[m054] post-move invariant: %d cents ok=%s", total_cents, invariant_ok,
    )
    if not invariant_ok:
        logger.critical(
            "[m054] INVARIANT BROKEN — sum=%d. Not recording gate.", total_cents,
        )
        return {"invariant_ok": False, "sum_cents": total_cents}

    record(conn, _MIGRATION_NAME)
    return {
        "invariant_ok": True,
        "sum_cents": total_cents,
        "from": {"bot": _FROM_BOT, "was": from_current, "now": from_new},
        "to":   {"bot": _TO_BOT,   "was": to_current,   "now": to_new},
        "executed": True,
    }
