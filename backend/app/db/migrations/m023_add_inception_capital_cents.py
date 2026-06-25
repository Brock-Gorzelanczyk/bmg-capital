"""m023 — Add inception_capital_cents + current_capital_cents to bot_allocations.

The clean-slate restart overwrote starting_capital_cents with the new
$1M-split amounts. That silently broke historical all-time return math —
canonical.compute_*_snapshot was dividing realized P&L by today's
starting_capital_cents (new amount) instead of the original inception
baseline used to compute the +3.30% etc. on the leaderboard.

This migration:
  1. Adds inception_capital_cents (nullable INTEGER).
  2. Adds current_capital_cents (nullable INTEGER).
  3. Backfills inception_capital_cents per-profile from the historical
     _PORTFOLIO_DEFS seed amounts (see backend/app/routers/bots.py:89):
       stock_*, crypto_swing/day/lt/onchain, options_*  → $100,000
       crypto_quant_aggressive                          → $40,000
       crypto_quant_scalper, crypto_quant_mean_reversion → $30,000
       cash_floor (new today, no history)               → starting value
       anything else                                    → starting value
  4. Backfills current_capital_cents = current starting_capital_cents.

Idempotent. Columns only added if missing; backfills only fire on rows
where the column is NULL.

After this migration runs, canonical.compute_bot_snapshot and
compute_portfolio_snapshot should be updated to use inception_capital_cents
as the denominator for all_time_return_pct. starting_capital_cents stays
as the "what is this bot's current allocation" field — the leaderboard
"$X / $Y deployed" display reads that.
"""
from __future__ import annotations

import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)

# Historical seed amounts at inception (cents) — see _PORTFOLIO_DEFS
HISTORICAL_INCEPTION_CENTS = {
    "stock_swing":                  10_000_000,
    "stock_day":                    10_000_000,
    "stock_lt":                     10_000_000,
    "crypto_swing":                 10_000_000,
    "crypto_day":                   10_000_000,
    "crypto_lt":                    10_000_000,
    "crypto_onchain":               10_000_000,
    "options_directional":          10_000_000,
    "options_income":               10_000_000,
    "crypto_quant_aggressive":       4_000_000,
    "crypto_quant_scalper":          3_000_000,
    "crypto_quant_mean_reversion":   3_000_000,
}


def _column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return any(r[1] == column for r in rows)


def _table_exists(conn, table: str) -> bool:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall() or []
    return bool(rows)


def run(conn) -> dict:
    added: list[str] = []

    if not _table_exists(conn, "bot_allocations"):
        return {"skipped_reason": "bot_allocations missing"}

    if not _column_exists(conn, "bot_allocations", "inception_capital_cents"):
        conn.execute(text(
            "ALTER TABLE bot_allocations ADD COLUMN inception_capital_cents INTEGER"
        ))
        added.append("inception_capital_cents")

    if not _column_exists(conn, "bot_allocations", "current_capital_cents"):
        conn.execute(text(
            "ALTER TABLE bot_allocations ADD COLUMN current_capital_cents INTEGER"
        ))
        added.append("current_capital_cents")

    # Backfill inception_capital_cents from historical seed amounts.
    # Only rows where inception is still NULL get touched.
    inception_set = 0
    for profile_name, cents in HISTORICAL_INCEPTION_CENTS.items():
        n = conn.execute(text("""
            UPDATE bot_allocations
               SET inception_capital_cents = :cents
             WHERE inception_capital_cents IS NULL
               AND profile_id IN (SELECT id FROM bot_profiles WHERE name = :name)
        """), {"cents": cents, "name": profile_name}).rowcount
        inception_set += int(n or 0)

    # Anything still NULL (e.g., cash_floor created today, or future new
    # profiles) gets seeded with whatever its current starting_capital_cents
    # is. That's the best we have for a "no historical reference" case.
    n_fallback = conn.execute(text("""
        UPDATE bot_allocations
           SET inception_capital_cents = starting_capital_cents
         WHERE inception_capital_cents IS NULL
    """)).rowcount
    inception_set += int(n_fallback or 0)

    # current_capital_cents = whatever starting_capital_cents reads right now
    # (this column is the place to mutate later if Brock wants to track
    # capital adjustments separately from inception baseline).
    current_set = conn.execute(text("""
        UPDATE bot_allocations
           SET current_capital_cents = starting_capital_cents
         WHERE current_capital_cents IS NULL
    """)).rowcount

    conn.commit()
    logger.warning(
        "[m023] added=%s · inception_backfilled=%d (fallback=%d) · current_backfilled=%d",
        added, inception_set, n_fallback, int(current_set or 0),
    )
    return {
        "added": added,
        "inception_backfilled_rows": inception_set,
        "inception_fallback_rows": int(n_fallback or 0),
        "current_backfilled_rows": int(current_set or 0),
    }
