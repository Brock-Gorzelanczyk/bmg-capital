"""m069 — Seed 3 SSRN-cited stock factor bots (dry-run, $0 capital).

Adds three new portfolio_rank_bots based on the BMG Strategy Knowledge
Vault v1 (`Strategy Library/BMG-Strategy-Knowledge-Vault-v1.md`):

  low_volatility          — Tier A. Blitz-van Vliet 2007 (SSRN 980865)
                            + Ang-Hodrick-Xing-Zhang 2006 (SSRN 647981)
  value_hml               — Tier B highest. Fama-French 1993 (SSRN 5233)
                            with intangibles adjustment per Arnott 2021
  net_stock_issuance      — Tier B "remarkably persistent". Pontiff-
                            Woodgate 2008 (SSRN 970586)

## Capital

Zero. Same pattern as m066 (momentum_umd + quality_gross_profitability
before m067 funded them). Brock's rule: no new capital, reallocate from
existing. These bots ship at $0 so a follow-up migration can fund them
from a specific source (crypto quant scalp trim, options over-allocation
if the 5%→8% cap change frees capacity, etc.) with the same guardrails
m067 used.

## Dry-run gate

All three bots ship enabled=false. Even if BMG_PORTFOLIO_RANK_BOTS_ENABLED
is true, they will not rebalance until an explicit UPDATE flips
enabled=1 on each. This matches the Phase 2 canary path.

## Fund invariant

Total = $1,000,000 exact. Bots at $0 → sum unchanged. Invariant asserted
post-mutation.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m069_ssrn_stock_factors_batch_2026_07"


_BOTS = [
    {
        "name": "low_volatility",
        "description": "Blitz-van Vliet 2007 / Ang-Hodrick-Xing-Zhang 2006. "
                       "Rank S&P 500 by trailing 21-day daily-return volatility "
                       "and long the bottom decile (lowest vol). Long-only, "
                       "sector-neutral where feasible. Monthly rebalance.",
        "factor_definition": {"kind": "low_volatility", "window_days": 21},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "monthly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 0,
        "enabled": 0,
        "paper_citation": "Blitz & van Vliet 2007 + Ang et al. 2006, SSRN 980865 / 647981",
        "ssrn_id": "980865",
    },
    {
        "name": "value_hml",
        "description": "Fama-French 1993 HML with intangibles adjustment "
                       "(Arnott et al. 2021). Rank S&P 500 by (Book Equity + "
                       "capitalized R&D + 0.3 * SG&A) / Market Equity. Long "
                       "top decile. Annual rebalance.",
        "factor_definition": {"kind": "value_hml"},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "quarterly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 0,
        "enabled": 0,
        "paper_citation": "Fama & French 1993, SSRN 5233",
        "ssrn_id": "5233",
    },
    {
        "name": "net_stock_issuance",
        "description": "Pontiff & Woodgate 2008. Rank S&P 500 by negative "
                       "log-growth in shares outstanding over the trailing "
                       "year. Long top decile (net repurchasers). Annual "
                       "rebalance.",
        "factor_definition": {"kind": "net_stock_issuance"},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "quarterly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 0,
        "enabled": 0,
        "paper_citation": "Pontiff & Woodgate 2008, SSRN 970586",
        "ssrn_id": "970586",
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

    # Invariant sanity check
    ba_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    ba_total = int(ba_row[0] or 0) if ba_row else 0
    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) FROM portfolio_rank_bots"
    )).fetchone()
    pr_total = int(pr_row[0] or 0) if pr_row else 0
    fund_total = ba_total + pr_total
    invariant_ok = fund_total == 100_000_000

    logger.warning(
        "[m069] invariant post-check: bot_allocations=$%d "
        "portfolio_rank_bots=$%d fund_total=$%d invariant_ok=%s",
        ba_total // 100, pr_total // 100, fund_total // 100, invariant_ok,
    )

    if not invariant_ok:
        raise RuntimeError(
            f"m069 invariant broken: fund_total={fund_total} "
            f"delta={fund_total - 100_000_000}"
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "seeded_bots": inserted,
        "fund_total_cents": fund_total,
        "invariant_ok": True,
    }
