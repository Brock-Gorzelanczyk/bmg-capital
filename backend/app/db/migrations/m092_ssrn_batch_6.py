"""m092 — SSRN batch 6: halt crypto_quant_defi_l2 + seed 3 new PR bots.

The last surviving sim-only crypto quant (crypto_quant_defi_l2, -$28.33
all-time on 50 trades, -0.97%) frees $2,920.20 to fund three new
portfolio-rank bots from SSRN batch 6:

  os_ratio           — Roll-Schwartz-Subrahmanyam 2010 / Johnson-So 2012.
                       Option volume / stock volume ratio, weekly rebal.
                       $1,000 seed.
  overnight_momentum — Lou-Polk-Skouras 2019. Sum of overnight (close→open)
                       returns. Daily rebal.
                       $1,000 seed.
  smart_money_13f    — Frazzini-Lamont 2008. Δ hedge-fund holdings via SEC
                       13F filings. Quarterly rebal. Reads from
                       smart_money_13f_holdings cache — degrades to empty
                       scores until the EDGAR ingest job ships.
                       $920.20 seed (smaller until the fetcher lands).

Sums exact to $2,920.20 (100,000 + 100,000 + 92,020 = 292,020 cents).
Fund invariant $96,826.70 preserved.

Idempotent via _gate.record() AND via data-level checks (halt won't
double-fire if already at cap=0; seed skips if bot already exists).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m092_ssrn_batch_6_2026_07_12"
_HALT_REASON = "halt_sim_only_bleeder_2026_07_12"
_HALT_BOT = "crypto_quant_defi_l2"

_PR_NEW = [
    {
        "name": "os_ratio",
        "description": (
            "Roll-Schwartz-Subrahmanyam 2010 / Johnson-So 2012 O/S ratio: "
            "sum(option volume) / avg stock volume. Cross-sectional "
            "informed-flow signal. Long bottom quintile (low O/S), weekly "
            "rebal. Complements cw_vol_spread — CW reads IV asymmetry, "
            "this reads volume asymmetry."
        ),
        "factor_definition": {"kind": "os_ratio",
                              "dte_max": 45, "stock_vol_days": 5,
                              "min_option_vol": 100},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "weekly",
        "long_decile": 20, "short_decile": 0,  # long bottom quintile
        "position_sizing": "equal_weight",
        "starting_capital_cents": 100_000,  # $1,000
        "enabled": 1,
        "paper_citation": "Roll-Schwartz-Subrahmanyam 2010 + Johnson-So 2012 JFE 106(2)",
        "ssrn_id": "1410091",
    },
    {
        "name": "overnight_momentum",
        "description": (
            "Lou-Polk-Skouras 2019 JFE overnight momentum. Score = sum of "
            "prior-21d overnight returns (close→open only, intraday "
            "discarded). Long top decile daily. Uncorrelated with 12-1 UMD "
            "because that signal is total return; this is close-to-open only."
        ),
        "factor_definition": {"kind": "overnight_momentum",
                              "lookback_days": 21},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "daily",
        "long_decile": 10, "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 100_000,  # $1,000
        "enabled": 1,
        "paper_citation": "Lou-Polk-Skouras 2019 JFE 134(1):192-213",
        "ssrn_id": "2687977",
    },
    {
        "name": "smart_money_13f",
        "description": (
            "Frazzini-Lamont 2008 hedge-fund holdings follow. Δ shares held "
            "by top-100 hedge funds (SEC 13F-HR filings) as cross-sectional "
            "signal. Long accumulations, short distributions. Quarterly "
            "rebal with 45-day filing lag. Currently seeded but scores "
            "empty until the smart_money_13f_holdings ingest job ships."
        ),
        "factor_definition": {"kind": "smart_money_13f",
                              "top_n_funds": 100,
                              "min_holdings": 30},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "quarterly",
        "long_decile": 10, "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 92_020,   # $920.20
        "enabled": 1,
        "paper_citation": "Frazzini-Lamont 2008 JFE 88(2):299-322",
        "ssrn_id": "419980",
    },
]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # ── 1. Halt crypto_quant_defi_l2 ──────────────────────────────────────
    row = conn.execute(text("""
        SELECT ba.id, ba.starting_capital_cents
          FROM bot_allocations ba
          JOIN bot_profiles bp ON bp.id = ba.profile_id
         WHERE ba.user_id = 1 AND bp.name = :n
         LIMIT 1
    """), {"n": _HALT_BOT}).fetchone()
    if row:
        alloc_id = int(row[0])
        prior = int(row[1] or 0)
        if prior <= 0:
            actions.append({"halt": "already_halted", "bot": _HALT_BOT,
                            "prior_cents": prior})
        else:
            conn.execute(text(
                "UPDATE bot_allocations "
                "SET enabled = 0, "
                "    starting_capital_cents = 0, "
                "    current_capital_cents = 0, "
                "    paused_reason = :r, "
                "    updated_at = :ts "
                "WHERE id = :aid"
            ), {"r": _HALT_REASON, "ts": now_iso, "aid": alloc_id})
            actions.append({"halt": "applied", "bot": _HALT_BOT,
                            "prior_cents": prior, "alloc_id": alloc_id})
    else:
        actions.append({"halt": "bot_not_found", "bot": _HALT_BOT})

    # ── 2. Seed the 3 new PR bots ─────────────────────────────────────────
    for b in _PR_NEW:
        existing = conn.execute(text(
            "SELECT id, starting_capital_cents FROM portfolio_rank_bots WHERE name = :n"
        ), {"n": b["name"]}).fetchone()
        if existing:
            actions.append({"seed": "already_exists", "bot": b["name"],
                            "cents": int(existing[1] or 0)})
            continue

        conn.execute(text("""
            INSERT INTO portfolio_rank_bots
              (name, description, factor_definition, universe,
               rebalance_schedule, long_decile, short_decile,
               position_sizing, starting_capital_cents, enabled,
               paper_citation, ssrn_id, created_at)
            VALUES
              (:name, :desc, :fdef, :uni, :sched, :ld, :sd, :ps,
               :cap, :en, :cite, :ssrn, :ts)
        """), {
            "name": b["name"], "desc": b["description"],
            "fdef": json.dumps(b["factor_definition"]),
            "uni":  json.dumps(b["universe"]),
            "sched": b["rebalance_schedule"],
            "ld": b["long_decile"], "sd": b["short_decile"],
            "ps": b["position_sizing"],
            "cap": b["starting_capital_cents"],
            "en":  b["enabled"],
            "cite": b["paper_citation"],
            "ssrn": b["ssrn_id"],
            "ts": now_iso,
        })
        actions.append({"seed": "inserted", "bot": b["name"],
                        "cents": b["starting_capital_cents"]})

    logger.warning("[m092] actions=%s", actions)
    record(conn, _MIGRATION_NAME)
    return {"executed": True, "actions": actions}
