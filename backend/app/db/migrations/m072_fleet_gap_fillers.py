"""m072 — Seed 2 fleet-gap-filler portfolio-rank bots (dry-run, $0 capital).

Session recommendation identified 4 major gaps in the current 29-bot
fleet coverage:
  1. No trend-following (across bonds, commodities, equity, FX)
  2. No delta-neutral crypto plays
  3. No pure idiosyncratic vol harvesting
  4. No analyst-revision signal-trigger

This migration ships #1 and #3 as portfolio-rank bots (clean fit with
existing infrastructure). #2 needs Kraken Futures broker integration
and #4 needs a paid analyst-data feed — both larger follow-up
projects.

## Seeded bots

  tsm_12m                 Moskowitz-Ooi-Pedersen 2012 (SSRN 1657676).
                          Rank 30 liquid ETFs by 12-month cumulative
                          return. Long top decile. Monthly rebalance.
                          Fills the trend-following gap in the fleet.

  idio_volatility         Ang-Hodrick-Xing-Zhang 2006 (SSRN 647981).
                          Rank S&P 500 by market-model residual std
                          over trailing 21 days. Long lowest-IVOL
                          decile. Monthly rebalance. Distinct from
                          low_volatility (which uses total vol).

Both ship at $0 capital + enabled=false. Same pattern as m066/m069.
A later migration allocates real capital when Brock decides the
source.

## Fund invariant

$1,000,000 exact before and after.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m072_fleet_gap_fillers_2026_07"


_BOTS = [
    {
        "name": "tsm_12m",
        "description": "Moskowitz-Ooi-Pedersen 2012 time-series momentum, "
                       "adapted to cross-sectional portfolio-rank framework. "
                       "Rank 30 liquid ETFs (equity, bonds, commodities, "
                       "sectors) by 12-month cumulative return. Long top "
                       "decile. Monthly rebalance. Fills the fleet's "
                       "trend-following gap.",
        "factor_definition": {"kind": "tsm_12m", "lookback_months": 12},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "etf_liquid"},
        "rebalance_schedule": "monthly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 0,
        "enabled": 0,
        "paper_citation": "Moskowitz, Ooi & Pedersen 2012, SSRN 1657676",
        "ssrn_id": "1657676",
    },
    {
        "name": "idio_volatility",
        "description": "Ang-Hodrick-Xing-Zhang 2006. Rank S&P 500 by "
                       "market-model residual std (regress ticker returns "
                       "on SPY over trailing 21 days). Long the lowest-IVOL "
                       "decile. Monthly rebalance. Distinct from "
                       "low_volatility which uses total vol.",
        "factor_definition": {"kind": "idio_volatility", "window_days": 21},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "monthly",
        "long_decile": 10,
        "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 0,
        "enabled": 0,
        "paper_citation": "Ang, Hodrick, Xing & Zhang 2006, SSRN 647981",
        "ssrn_id": "647981",
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
            f"m072 invariant broken: fund_total={fund_total} != 100000000"
        )

    record(conn, _MIGRATION_NAME)
    return {"executed": True, "seeded_bots": inserted,
            "fund_total_cents": fund_total, "invariant_ok": True}
