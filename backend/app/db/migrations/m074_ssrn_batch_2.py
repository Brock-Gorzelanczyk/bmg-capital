"""m074 — Seed 2 more SSRN factor bots + fund at $10k each.

Second SSRN batch based on 2026-07-07 4-agent research pass:
  1. Residual Momentum (Blitz-Huij-Martens 2011, SSRN 2319861)
     ~2x Sharpe of raw 12-1 momentum; strip market/size/value
     factor exposure then rank on residual return.
  2. Betting Against Beta (Frazzini-Pedersen 2014, SSRN 2049939)
     Long-only low-beta variant; complements low_volatility
     (total vol) with beta-neutral construction.

Both funded at $10k, enabled. Funding source: trim momentum_umd
$35k → $25k and quality_gross_profitability $35k → $25k, freeing
$20k for the 2 new bots.

Post-migration portfolio-rank allocation:
  momentum_umd                  $25,000  (was $35k, was $50k)
  quality_gross_profitability   $25,000  (was $35k, was $50k)
  low_volatility                $10,000
  value_hml                     $10,000
  net_stock_issuance            $10,000
  residual_momentum             $10,000  (NEW)
  bab                           $10,000  (NEW)
  --------
  TOTAL                        $100,000

Fund invariant $1M exact before and after.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m074_ssrn_batch_2_2026_07"


_TRIMS = [
    ("momentum_umd", 3_500_000, 2_500_000),
    ("quality_gross_profitability", 3_500_000, 2_500_000),
]


_NEW_BOTS = [
    {
        "name": "residual_momentum",
        "description": (
            "Blitz-Huij-Martens 2011, SSRN 2319861. Rank S&P 500 by "
            "cumulative residual return from a market-model regression "
            "on SPY over trailing 12 months (skip most recent). Long "
            "top decile. ~2x Sharpe of raw 12-1 momentum with fewer "
            "crashes."
        ),
        "factor_definition": {
            "kind": "residual_momentum",
            "lookback_months": 12,
            "skip_months": 1,
        },
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "monthly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 1_000_000,
        "enabled": 1,
        "paper_citation": "Blitz, Huij & Martens 2011, SSRN 2319861",
        "ssrn_id": "2319861",
    },
    {
        "name": "bab",
        "description": (
            "Frazzini-Pedersen 2014 Betting Against Beta, SSRN 2049939. "
            "Long-only variant: rank S&P 500 by trailing 252-day beta "
            "vs SPY, long lowest-beta decile. Complements low_volatility "
            "(total vol) by isolating systematic-risk exposure."
        ),
        "factor_definition": {"kind": "bab", "lookback_days": 252},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "monthly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 1_000_000,
        "enabled": 1,
        "paper_citation": "Frazzini & Pedersen 2014, SSRN 2049939",
        "ssrn_id": "2049939",
    },
]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    actions: list[dict] = []

    # Pre-flight — verify current PR state
    for name, expect, _new in _TRIMS:
        row = conn.execute(text(
            "SELECT starting_capital_cents, enabled "
            "FROM portfolio_rank_bots WHERE name = :n"
        ), {"n": name}).fetchone()
        if not row:
            raise RuntimeError(f"m074 pre-flight: {name} not found")
        if int(row[0] or 0) != expect:
            raise RuntimeError(
                f"m074 pre-flight: {name} capital={row[0]} != expected {expect}"
            )

    # 1. Trim the 2 existing bots
    for name, _old, new in _TRIMS:
        conn.execute(text(
            "UPDATE portfolio_rank_bots "
            "SET starting_capital_cents = :c WHERE name = :n"
        ), {"c": new, "n": name})
        actions.append({"bot": name, "action": "trim", "new_cents": new})
        logger.warning("[m074] trimmed %s to %d cents", name, new)

    # 2. Insert the 2 new SSRN bots (funded + enabled)
    now_iso = datetime.now(timezone.utc).isoformat()
    inserted = 0
    for b in _NEW_BOTS:
        existing = conn.execute(text(
            "SELECT id FROM portfolio_rank_bots WHERE name = :n"
        ), {"n": b["name"]}).fetchone()
        if existing:
            actions.append({"bot": b["name"], "action": "already_exists"})
            continue
        conn.execute(text("""
            INSERT INTO portfolio_rank_bots
              (name, description, factor_definition, universe,
               rebalance_schedule, long_decile, short_decile,
               position_sizing, starting_capital_cents, enabled,
               paper_citation, ssrn_id, created_at)
            VALUES
              (:name, :desc, :fdef, :uni, :sched, :ld, :sd,
               :ps, :cap, :en, :cite, :ssrn, :ts)
        """), {
            "name": b["name"],
            "desc": b["description"],
            "fdef": json.dumps(b["factor_definition"]),
            "uni":  json.dumps(b["universe"]),
            "sched": b["rebalance_schedule"],
            "ld":   b["long_decile"],
            "sd":   b["short_decile"],
            "ps":   b["position_sizing"],
            "cap":  b["starting_capital_cents"],
            "en":   b["enabled"],
            "cite": b["paper_citation"],
            "ssrn": b["ssrn_id"],
            "ts":   now_iso,
        })
        inserted += 1
        actions.append({
            "bot": b["name"],
            "action": "seeded_funded_enabled",
            "cents": b["starting_capital_cents"],
        })
        logger.warning("[m074] seeded %s at %d cents enabled=1",
                       b["name"], b["starting_capital_cents"])

    # 3. Fund invariant check
    ba_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) FROM portfolio_rank_bots"
    )).fetchone()
    fund_total = int(ba_row[0] or 0) + int(pr_row[0] or 0)

    if fund_total != 100_000_000:
        raise RuntimeError(
            f"m074 invariant broken: fund_total={fund_total} != 100000000 "
            f"(ba={ba_row[0]}, pr={pr_row[0]})"
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "actions": actions,
        "seeded_bots": inserted,
        "fund_total_cents": fund_total,
        "invariant_ok": True,
    }
