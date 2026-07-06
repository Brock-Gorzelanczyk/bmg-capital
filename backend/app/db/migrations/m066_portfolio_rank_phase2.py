"""m066 — Portfolio-Rank Phase 2: two real anomaly bots seeded (dry-run).

Ships momentum_umd and quality_gross_profitability as `portfolio_rank_bots`
rows. Both are disabled at insert time so nothing happens until Brock
flips BMG_PORTFOLIO_RANK_BOTS_ENABLED=true and hits the manual rebalance
endpoint. Even then, the runner stays in dry-run mode until Brock also
flips BMG_PORTFOLIO_RANK_LIVE_ORDERS=true.

## Capital funding note (important)

The Phase 2 spec called for $50K starting capital per bot, funded by
reducing the Cash Floor bot_allocation by $100K. Reviewing the actual
capital state before writing this migration:

  cash_floor bot_allocation = $10,000 (1_000_000 cents, per m062)

Not $100K, not $721K. The $721K figure in the spec was the fleet's
UNDEPLOYED CASH (fund PV minus deployed notional), which lives inside
each bot's allocation, not in the cash_floor line item. Cash Floor is
just one row in bot_allocations with a small allocation.

Rather than silently take a wrong funding source and break the $1M
invariant, this migration seeds both bots with starting_capital_cents=0.
Dry-run still exercises the full pipeline (ranking, basket build,
holdings write, Discord digest). Fund total stays at $1,000,000 exact.

Funding decision punted to Brock's next paste-ready. Options:
  A. Reduce cash_floor to $0 ($10K freed) + take $45K each from
     crypto_quant_scalp_1m ($20K → $0) + crypto_quant_10m ($20K → $0)
     + crypto_quant_15m ($20K → $0) + crypto_quant_meme_tier ($10K → $0)
     = $80K freed → not quite $100K but close, would zero four
     underperforming crypto quants.
  B. Reduce crypto_quant_aggressive from $130K to $30K → frees $100K
     from the biggest quant bot. Currently +2.77% today; not a loser.
     Real behavioral change to an active bot.
  C. Wait for fleet realized P&L to accumulate $100K, fund from that.
     Slower but respects the "no new money, no cuts on P&L" pair.

None of these are decisions I can make. This migration ships the
plumbing at $0 capital and preserves the invariant.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m066_portfolio_rank_phase2_2026_07"


_BOTS = [
    {
        "name": "momentum_umd",
        "description": "12-1 momentum (Jegadeesh-Titman 1993). Rank S&P 500 by "
                       "cumulative return from t-13m to t-1m; hold top decile "
                       "long, equal-weighted, rebalance monthly.",
        "factor_definition": {"kind": "return_lookback",
                              "months_back": 12, "skip_months": 1},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "monthly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        # 0 by design — see docstring above. Real capital allocation is
        # a follow-up migration once Brock picks the funding source.
        "starting_capital_cents": 0,
        "enabled": 0,
        "paper_citation": "Jegadeesh & Titman 1993, SSRN 227615",
        "ssrn_id": "227615",
    },
    {
        "name": "quality_gross_profitability",
        "description": "Novy-Marx quality (2013). Rank S&P 500 by GP/A = "
                       "(Revenue_ttm - COGS_ttm) / Total_Assets; hold top "
                       "decile long, equal-weighted, rebalance quarterly.",
        "factor_definition": {"kind": "novy_marx_gp_a"},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "quarterly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 0,
        "enabled": 0,
        "paper_citation": "Novy-Marx 2013, SSRN 2049783",
        "ssrn_id": "2049783",
    },
]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    inserted = 0
    for b in _BOTS:
        existing = conn.execute(text(
            "SELECT id FROM portfolio_rank_bots WHERE name = :n"
        ), {"n": b["name"]}).fetchone()
        if existing:
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
            "ts":   datetime.now(timezone.utc).isoformat(),
        })
        inserted += 1

    # Invariant check: fund total should be exactly $1M in cents = 100_000_000.
    # Since we did NOT touch bot_allocations and both new bots have $0
    # capital, this should hold trivially. Log the result so the invariant
    # is asserted at migration time, not silently at boot.
    inv_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    bot_alloc_total = int(inv_row[0] or 0) if inv_row else 0
    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM portfolio_rank_bots"
    )).fetchone()
    pr_total = int(pr_row[0] or 0) if pr_row else 0
    fund_total = bot_alloc_total + pr_total
    logger.warning(
        "[m066] invariant post-check: bot_allocations=$%d.%02d "
        "portfolio_rank_bots=$%d.%02d fund_total=$%d.%02d "
        "(target $1,000,000.00)",
        bot_alloc_total // 100, bot_alloc_total % 100,
        pr_total // 100, pr_total % 100,
        fund_total // 100, fund_total % 100,
    )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "seeded_bots": inserted,
        "bot_allocations_total_cents": bot_alloc_total,
        "portfolio_rank_bots_total_cents": pr_total,
        "fund_total_cents": fund_total,
        "invariant_ok": fund_total == 100_000_000,
    }
