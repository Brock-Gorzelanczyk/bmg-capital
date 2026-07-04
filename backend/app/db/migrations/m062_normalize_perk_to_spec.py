"""m062 — Normalize Perk (user_id=7) to the same $1M spec as Brock.

Brock's audit 2026-07-03 found Perk's account at $4,030,000 — 4x his
own $1,000,000 spec. Root cause: m025, m026, m057, m058, m059, m061 all
filter `user_id = 1` when normalizing allocations. Perk's account was
seeded via _ensure_portfolios_for_user with the legacy $100k-per-bot
default and never re-normalized.

Brock's directive (2026-07-03): "APPROVE Option A — normalize Perk to
your $1M spec."

## Target (identical to Brock's post-m061 state)

Sums to exactly $100_000_000 cents = $1,000,000.

## Halted / zeroed / killed bots

Also set to $0 for Perk, matching Brock's state:
  crypto_quant_mean_reversion  (halted)
  crypto_quant_scalper          (halted)
  crypto_onchain                (killed by m061)
  crypto_meanrev_2163           (Perk-only leftover, zero it)
  stock_quant_day_meanrev / day_momentum / swing_growth / swing_value

## Method

Idempotent bulk update: set every user_id=7 allocation to the target
value (or $0 if not in the table). No new capital added — just
redistributed within Perk's existing 29 allocations. Fund invariant
verified before recording gate.

## No env-var gate

Brock explicitly approved. This is spec-driven, not autonomous.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m062_normalize_perk_2026_07"
_PERK_USER_ID = 7
_INVARIANT_TARGET = 100_000_000  # $1,000,000 exact

# Same target as Brock's post-m061 state (m057 base + m058 redistribution + m061 aggressive bump).
_TABLE: dict[str, int] = {
    # Stocks — 3 originals + 4 new stock traders
    "stock_swing":                  9_000_000,
    "stock_lt":                     8_000_000,
    "stock_day":                    7_000_000,
    "stock_gap_fade":               4_000_000,
    "stock_orb_breakout":           4_000_000,
    "stock_momentum_breakout":      4_000_000,
    "stock_pead":                   4_000_000,
    # Crypto — 4 originals + 8 quant batch
    "crypto_day":                   8_000_000,
    "crypto_swing":                 6_000_000,
    "crypto_lt":                    5_000_000,
    "crypto_quant_scalp_1m":        2_000_000,
    "crypto_quant_10m":             2_000_000,
    "crypto_quant_15m":             2_000_000,
    "crypto_quant_universe_top6":   2_000_000,
    "crypto_quant_alt_focus":       3_000_000,
    "crypto_quant_defi_l2":         3_000_000,
    "crypto_quant_meme_tier":       1_000_000,
    "crypto_dca_btc_eth":           2_000_000,
    # Options
    "options_directional":          5_000_000,
    "options_income":               5_000_000,
    # Quant sleeve
    "crypto_quant_aggressive":     13_000_000,  # $130k post-m061
    # Cash
    "cash_floor":                   1_000_000,
}


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    user_row = conn.execute(text(
        "SELECT id FROM users WHERE id = :uid"
    ), {"uid": _PERK_USER_ID}).fetchone()
    if not user_row:
        return {"skipped_reason": "no_perk_user", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # 1. INSERT any missing allocations for target bots that Perk doesn't have.
    # (Perk was missing cash_floor entirely — caused first m062 run to land
    # at $990K instead of $1M.)
    existing_names = {r[0] for r in conn.execute(text(
        "SELECT p.name FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid"
    ), {"uid": _PERK_USER_ID}).fetchall()}

    for bot_name, target_cents in _TABLE.items():
        if bot_name in existing_names or target_cents == 0:
            continue
        # Look up profile_id
        prof_row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": bot_name}).fetchone()
        if not prof_row:
            actions.append({"bot": bot_name, "action": "profile_not_found_skipped"})
            continue
        conn.execute(text(
            "INSERT INTO bot_allocations "
            "(user_id, profile_id, capital_pct, risk_profile, paper_mode, "
            " go_live_requested, enabled, starting_capital_cents, tier, "
            " created_at, updated_at) "
            "VALUES (:uid, :pid, 10.0, 'standard', 1, 0, 1, :c, 'T0', "
            "        :now, :now)"
        ), {"uid": _PERK_USER_ID, "pid": int(prof_row[0]),
            "c": target_cents, "now": now_iso})
        actions.append({
            "bot": bot_name,
            "action": "inserted_missing",
            "cents": target_cents,
        })
        logger.warning("[m062] Perk INSERTED missing allocation for %s @ %d", bot_name, target_cents)

    # 2. UPDATE existing allocations to their target values.
    rows = conn.execute(text(
        "SELECT a.id, a.starting_capital_cents, p.name "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid"
    ), {"uid": _PERK_USER_ID}).fetchall()

    for alloc_id, current_cents, bot_name in rows:
        current_cents = int(current_cents or 0)
        target_cents = _TABLE.get(bot_name, 0)  # bots not in table → $0
        if current_cents == target_cents:
            actions.append({"bot": bot_name, "action": "already_target", "cents": current_cents})
            continue
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET starting_capital_cents = :c, updated_at = :now "
            "WHERE id = :aid"
        ), {"c": target_cents, "now": now_iso, "aid": int(alloc_id)})
        actions.append({
            "bot": bot_name,
            "alloc_id": int(alloc_id),
            "action": "reallocated",
            "from_cents": current_cents,
            "to_cents": target_cents,
            "delta_cents": target_cents - current_cents,
        })
        logger.warning(
            "[m062] Perk %s: %d → %d (delta %+d)",
            bot_name, current_cents, target_cents, target_cents - current_cents,
        )

    # Verify Perk's total sum == $1M.
    total_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": _PERK_USER_ID}).fetchone()
    total = int(total_row[0]) if total_row else 0
    invariant_ok = (total == _INVARIANT_TARGET)
    logger.warning(
        "[m062] Perk post-normalization sum: %d cents (target %d) ok=%s",
        total, _INVARIANT_TARGET, invariant_ok,
    )
    if not invariant_ok:
        logger.critical(
            "[m062] INVARIANT BROKEN — Perk sum=%d not $1M. Not recording gate.",
            total,
        )
        return {
            "invariant_ok": False,
            "user_id": _PERK_USER_ID,
            "sum_cents": total,
            "target_cents": _INVARIANT_TARGET,
            "actions": actions,
        }

    record(conn, _MIGRATION_NAME)
    return {
        "invariant_ok": True,
        "user_id": _PERK_USER_ID,
        "sum_cents": total,
        "actions_count": len(actions),
        "executed": True,
    }
