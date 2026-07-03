"""m057 — Brock's spec allocation table (2026-07-02 late-night ask).

Brock's directive (final, 2026-07-03 correction):
  "the capital to only be 1 million plus whatever we are up or down"

Meaning: sum(starting_capital_cents) across all user_id=1 bots MUST equal
exactly $1,000,000. Fund PV floats around $1M ± net P&L as position values
move. The $1M is the anchor; P&L is separate.

## Table correction

Brock's earlier table summed to $1,010,000 — a math error he caught. His
correction: cut Quant Mean Rev (HALTED) from $80k → $70k. Rationale:
Mean Rev is halted, capital sitting there is inert until a restart
decision; reducing it has zero real-world impact. Do NOT cut from any
active bot.

## Full allocation reset

Sets EVERY user_id=1 bot's starting_capital_cents to the exact value in
_TABLE. Bots NOT in the table get their capital set to $0 (this happens
to include the 4 stock_quant_* bots I autonomously created in m056, which
Brock's table excludes in favor of 4 different stock traders he specced:
stock_gap_fade / stock_orb_breakout / stock_momentum_breakout / stock_pead).

## Autonomy gate

This migration DOES capital moves on user 1's live fleet. Per Brock's
2026-07-02 autonomy rule ("Post to Discord BEFORE any capital moves,
Brock approves"), it is gated behind the environment variable
`BMG_APPROVE_M057`. Only when set to "true" (or "1") on Railway will the
migration execute. Otherwise it no-ops and returns `awaiting_approval`.

To activate:
  Railway → bmg-capital service → Variables → add BMG_APPROVE_M057=true
  → next deploy runs the migration once, records the gate, done.

## Idempotency

Standard _gate.already_ran / record pattern. Once the env var is set and
the migration executes cleanly, the gate is recorded and future boots
skip. Removing the env var after the fact has no effect.

## What Brock's table does NOT include (get set to $0)

- stock_quant_day_momentum (m056, autonomous)
- stock_quant_day_meanrev (m056, autonomous)
- stock_quant_swing_growth (m056, autonomous)
- stock_quant_swing_value (m056, autonomous)
- crypto_meanrev_2163 (T0 incubation)

If Brock wants any of these back later he can add them to a follow-up
migration.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m057_brock_reallocation_table_2026_07"
_APPROVE_ENV = "BMG_APPROVE_M057"
_INVARIANT_TARGET = 100_000_000  # $1,000,000 exact — Brock's final directive

# Brock's spec allocation (bot_name → cents). Bots not in this dict get $0.
_TABLE = {
    # Stocks — 3 originals + 4 new stock traders
    "stock_day":                    7_000_000,   # $70k
    "stock_lt":                     8_000_000,   # $80k
    "stock_swing":                  9_000_000,   # $90k
    "stock_gap_fade":               2_000_000,   # $20k
    "stock_orb_breakout":           2_000_000,   # $20k
    "stock_momentum_breakout":      2_000_000,   # $20k
    "stock_pead":                   2_000_000,   # $20k
    # Crypto — 4 originals + 8 quant batch
    "crypto_day":                   8_000_000,   # $80k
    "crypto_lt":                    5_000_000,   # $50k
    "crypto_swing":                 6_000_000,   # $60k
    "crypto_onchain":               3_000_000,   # $30k
    "crypto_quant_15m":             2_000_000,   # $20k
    "crypto_quant_10m":             2_000_000,   # $20k
    "crypto_quant_defi_l2":         2_000_000,   # $20k
    "crypto_quant_meme_tier":       1_000_000,   # $10k
    "crypto_quant_scalp_1m":        1_000_000,   # $10k
    "crypto_quant_universe_top6":   1_000_000,   # $10k
    "crypto_quant_alt_focus":       2_000_000,   # $20k
    "crypto_dca_btc_eth":           2_000_000,   # $20k
    # Options
    "options_directional":          5_000_000,   # $50k
    "options_income":               5_000_000,   # $50k
    # Quant sleeve (asset-agnostic original 3)
    "crypto_quant_aggressive":     10_000_000,   # $100k
    "crypto_quant_mean_reversion":  7_000_000,   # $70k (HALTED — trimmed $10k
                                                 # 2026-07-03 correction to
                                                 # bring total to $1M exact)
    "crypto_quant_scalper":         5_000_000,   # $50k (HALTED — funded per Brock)
    # Cash
    "cash_floor":                   1_000_000,   # $10k
}


def run(conn) -> dict:
    """Execute Brock's spec reallocation. Gated by env var."""
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
        logger.warning("[m057] user_id=1 missing — skip")
        return {"skipped_reason": "no_fund_user", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # 1. Fetch every user_id=1 allocation with its current capital + profile name.
    all_rows = conn.execute(text(
        "SELECT a.id, a.starting_capital_cents, p.name "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = 1"
    )).fetchall()

    # 2. For every allocation, set starting_capital to Brock's table value
    #    (or $0 if the bot is not in the table). Update updated_at.
    for alloc_id, current_cents, bot_name in all_rows:
        current_cents = int(current_cents or 0)
        target_cents = _TABLE.get(bot_name, 0)
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
            "[m057] %s starting_capital %d → %d (delta %+d)",
            bot_name, current_cents, target_cents, target_cents - current_cents,
        )

    # 3. Verify invariant: total sum matches Brock's table sum ($1,010,000).
    total_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    total_cents = int(total_row[0]) if total_row else 0
    invariant_ok = (total_cents == _INVARIANT_TARGET)
    logger.warning(
        "[m057] post-reallocation sum: %d cents (target %d) ok=%s",
        total_cents, _INVARIANT_TARGET, invariant_ok,
    )
    if not invariant_ok:
        logger.critical(
            "[m057] INVARIANT BROKEN — sum=%d not $%d. Not recording gate.",
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
