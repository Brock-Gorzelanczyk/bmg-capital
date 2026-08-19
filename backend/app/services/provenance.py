"""Provenance — origin ENUM for bot_trades / bot_positions.

Single source of truth for the origin values enforced by m099's trigger.
Import everywhere that constructs BotTrade or BotPosition rows, so a
runtime typo raises a NameError before hitting the DB.

Standing rule (CLAUDE.md §W1): BMG never writes a row that impersonates
a broker fact. Any row BMG generates must be labeled at the schema level.

Consumer filtering rule:
  - trade counts, round-trips, win-rate, Sharpe, realized_pnl → BROKER_FILL ONLY
  - positions / exposure / valuation / attribution        → ALL origins
  - UI blotter default                                    → BROKER_FILL
  - "system activity" view                                → ALL origins
"""
from __future__ import annotations

from typing import Optional

BROKER_FILL = "BROKER_FILL"  # real Alpaca fill (36-char UUID alpaca_order_id)
ADOPTED = "ADOPTED"          # from adopter (Alpaca position discovered, not submitted)
RECONCILE = "RECONCILE"      # from broker-recon (close on Alpaca-side disappearance)
REBUILD = "REBUILD"          # from rebuild jobs (order-history reconstruction)
BACKFILL = "BACKFILL"        # historical repair, dev scripts, migrations

ALLOWED_ORIGINS: tuple[str, ...] = (BROKER_FILL, ADOPTED, RECONCILE, REBUILD, BACKFILL)


# ── Convenience: SQL-friendly filter for consumers ────────────────────────

def only_broker_fills_clause(col_name: str = "origin") -> str:
    """SQL fragment for WHERE clauses. Use for count/round-trip/P&L queries.
    Example: text(f"SELECT COUNT(*) FROM bot_trades WHERE {only_broker_fills_clause()}")
    """
    return f"{col_name} = '{BROKER_FILL}'"


def infer_origin_from_alpaca_order_id(alpaca_order_id: Optional[str]) -> str:
    """Best-guess mapping matching the m099 backfill CASE. Callers should
    prefer setting origin explicitly at the write site; this helper exists
    only for reconstruction paths that don't know their own provenance."""
    if not alpaca_order_id:
        return BACKFILL
    oid = str(alpaca_order_id).strip()
    if len(oid) == 36 and oid.count("-") == 4:
        return BROKER_FILL
    if oid.startswith(("orphan_adopter", "adopter", "catchall_adopter_", "adopt_missing_")):
        return ADOPTED
    if oid.startswith("reconcile_close_"):
        return RECONCILE
    if oid.startswith("rebuild_"):
        return REBUILD
    return BACKFILL


def is_valid(origin: Optional[str]) -> bool:
    return origin in ALLOWED_ORIGINS


# ─── Ledger #34 / m100 helpers ────────────────────────────────────────────
# fill_price_cents rounds sub-penny fills (SHIB @ $0.000024) to 0.
# fill_price_micros (1e6 × dollars) preserves precision. Writers must set
# BOTH during the m100 deprecation window; the legacy cents value stays
# populated so consumers not yet migrated still work.

def price_to_micros(px_dollars: float) -> int:
    """Convert dollar price to micro-cents (1e6 × dollars). Never returns 0
    for a nonzero input — sub-penny is preserved. NaN/negative → 0."""
    try:
        v = float(px_dollars)
    except (TypeError, ValueError):
        return 0
    if v != v or v <= 0:  # NaN check via v != v
        return 0
    return int(round(v * 1_000_000))


def price_to_cents(px_dollars: float) -> int:
    """Legacy dollar → cents (int). Sub-penny truncates to 0 — that's the
    ledger #34 bug. Kept as a helper so writer sites use ONE consistent
    coercion. Writers should always call BOTH price_to_cents AND
    price_to_micros so both columns stay in sync during m100 window."""
    try:
        v = float(px_dollars)
    except (TypeError, ValueError):
        return 0
    if v != v or v <= 0:
        return 0
    return int(round(v * 100))
