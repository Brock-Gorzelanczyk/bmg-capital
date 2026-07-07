"""m075 — SSRN batch 3: PEAD + Insider + Crypto-XS + Faber + SPY Iron Condor.

Ships 3 new portfolio-rank factor bots and 2 new signal-trigger bots
funded at $10-15k each, all enabled. Trims existing bots to preserve
$1M fund invariant.

## Portfolio-rank additions (all $10k, enabled)
  pead                  — Bernard-Thomas post-earnings drift (SP500)
  insider_cluster_buys  — Cohen-Malloy-Pomorski (SP500)
  crypto_xs_momentum    — Liu-Tsyvinski-Wu (top-20 crypto)

## Signal-trigger additions
  macro_faber_gtaa       — $15k. 5-ETF Faber 10-mo SMA rule.
  spy_iron_condor_weekly — $15k. Weekly SPY 16-delta condor.

## Funding
PR sleeve: trim momentum_umd 25k→10k, quality 25k→10k = $30k freed.
Signal-trigger: trim cash_floor 10k→5k, options_directional 25k→20k,
  options_income 25k→20k, crypto_day 80k→70k, crypto_quant_aggressive
  80k→75k = $30k freed.

## Post-migration state
Portfolio-rank ($100k):
  momentum_umd                       $10k
  quality_gross_profitability        $10k
  low_volatility                     $10k
  value_hml                          $10k
  net_stock_issuance                 $10k
  residual_momentum                  $10k
  bab                                $10k
  pead                               $10k (NEW)
  insider_cluster_buys               $10k (NEW)
  crypto_xs_momentum                 $10k (NEW)

Signal-trigger ($900k): unchanged total, redistributed.

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

_MIGRATION_NAME = "m075_ssrn_batch_3_2026_07"

_BROCK_USER_ID = 1


_PR_TRIMS = [
    ("momentum_umd", 2_500_000, 1_000_000),
    ("quality_gross_profitability", 2_500_000, 1_000_000),
]

_PR_NEW = [
    {
        "name": "pead",
        "description": (
            "Bernard-Thomas Post-Earnings-Announcement Drift. Rank "
            "S&P 500 by cumulative return from day before earnings "
            "announcement to today, filtered to earnings in last 90 "
            "days. Long top decile of positive drift. Monthly rebal."
        ),
        "factor_definition": {"kind": "pead", "lookback_days": 90},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "monthly",
        "long_decile": 10, "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 1_000_000,
        "enabled": 1,
        "paper_citation": "Bernard & Thomas 1989 JAR",
        "ssrn_id": "",
    },
    {
        "name": "insider_cluster_buys",
        "description": (
            "Cohen-Malloy-Pomorski 2012 opportunistic insider signal. "
            "Rank S&P 500 by count of insider purchases in trailing "
            "90 days, scaled by log(purchase value). Long top decile. "
            "Monthly rebal. Data via yfinance insider_transactions."
        ),
        "factor_definition": {"kind": "insider_cluster_buys",
                              "lookback_days": 90},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "monthly",
        "long_decile": 10, "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 1_000_000,
        "enabled": 1,
        "paper_citation": "Cohen, Malloy & Pomorski 2012, NBER w16454",
        "ssrn_id": "",
    },
    {
        "name": "crypto_xs_momentum",
        "description": (
            "Liu-Tsyvinski-Wu 2022 JoF crypto momentum factor. Rank "
            "top-20 crypto pairs by trailing 7-day return. Long top "
            "decile. Weekly rebal."
        ),
        "factor_definition": {"kind": "crypto_xs_momentum",
                              "lookback_days": 7},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "crypto_top20"},
        "rebalance_schedule": "weekly",
        "long_decile": 10, "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 1_000_000,
        "enabled": 1,
        "paper_citation": "Liu, Tsyvinski & Wu 2022, SSRN 3379131",
        "ssrn_id": "3379131",
    },
]


# Signal-trigger allocations. Trim + fund.
_ST_TRIMS = [
    ("cash_floor",              1_000_000,  500_000),   # 10k -> 5k
    ("options_directional",     2_500_000, 2_000_000),  # 25k -> 20k
    ("options_income",          2_500_000, 2_000_000),  # 25k -> 20k
    ("crypto_day",              8_000_000, 7_000_000),  # 80k -> 70k
    ("crypto_quant_aggressive", 8_000_000, 7_500_000),  # 80k -> 75k
]

# New signal-trigger bots (each needs bot_profile + bot_allocation).
_ST_NEW = [
    {
        "profile_name": "macro_faber_gtaa",
        "starting_capital_cents": 1_500_000,  # 15k
    },
    {
        "profile_name": "spy_iron_condor_weekly",
        "starting_capital_cents": 1_500_000,  # 15k
    },
]


def _get_pr_bot(conn, name):
    return conn.execute(text(
        "SELECT starting_capital_cents, enabled FROM portfolio_rank_bots "
        "WHERE name = :n"
    ), {"n": name}).fetchone()


def _get_st_alloc(conn, profile_name, user_id):
    return conn.execute(text(
        "SELECT a.id, a.starting_capital_cents, a.enabled, p.id "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid AND p.name = :n"
    ), {"uid": user_id, "n": profile_name}).fetchone()


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # ── Pre-flight PR trims ──────────────────────────────────────────────
    for name, expect, _new in _PR_TRIMS:
        row = _get_pr_bot(conn, name)
        if not row:
            raise RuntimeError(f"m075 pre-flight: {name} PR bot not found")
        if int(row[0] or 0) != expect:
            raise RuntimeError(
                f"m075 pre-flight: PR {name} capital={row[0]} != expected {expect}"
            )

    # ── Pre-flight signal-trigger trims ──────────────────────────────────
    for pname, expect, _new in _ST_TRIMS:
        row = _get_st_alloc(conn, pname, _BROCK_USER_ID)
        if not row:
            raise RuntimeError(
                f"m075 pre-flight: signal-trigger {pname} allocation not found"
            )
        if int(row[1] or 0) != expect:
            raise RuntimeError(
                f"m075 pre-flight: ST {pname} capital={row[1]} != expected {expect}"
            )

    # ── 1. Trim PR bots ──────────────────────────────────────────────────
    for name, _old, new in _PR_TRIMS:
        conn.execute(text(
            "UPDATE portfolio_rank_bots SET starting_capital_cents = :c "
            "WHERE name = :n"
        ), {"c": new, "n": name})
        actions.append({"table": "pr", "bot": name, "action": "trim",
                        "new_cents": new})
        logger.warning("[m075] trimmed PR %s to %d cents", name, new)

    # ── 2. Seed new PR bots ──────────────────────────────────────────────
    for b in _PR_NEW:
        existing = conn.execute(text(
            "SELECT id FROM portfolio_rank_bots WHERE name = :n"
        ), {"n": b["name"]}).fetchone()
        if existing:
            actions.append({"table": "pr", "bot": b["name"],
                            "action": "already_exists"})
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
        actions.append({"table": "pr", "bot": b["name"],
                        "action": "seeded_funded_enabled",
                        "cents": b["starting_capital_cents"]})
        logger.warning("[m075] seeded PR %s at %d cents enabled=1",
                       b["name"], b["starting_capital_cents"])

    # ── 3. Trim signal-trigger allocations ───────────────────────────────
    for pname, _old, new in _ST_TRIMS:
        row = _get_st_alloc(conn, pname, _BROCK_USER_ID)
        alloc_id = int(row[0])
        conn.execute(text(
            "UPDATE bot_allocations SET starting_capital_cents = :c, "
            "updated_at = :ts WHERE id = :aid"
        ), {"c": new, "ts": now_iso, "aid": alloc_id})
        actions.append({"table": "st", "bot": pname, "action": "trim",
                        "new_cents": new})
        logger.warning("[m075] trimmed ST %s alloc_id=%d to %d cents",
                       pname, alloc_id, new)

    # ── 4. Create bot_profiles + bot_allocations for new signal-trigger ─
    for b in _ST_NEW:
        pname = b["profile_name"]
        # Get or create bot_profile
        prof = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": pname}).fetchone()
        if not prof:
            conn.execute(text(
                "INSERT INTO bot_profiles (name, enabled, created_at) "
                "VALUES (:n, 1, :ts)"
            ), {"n": pname, "ts": now_iso})
            prof = conn.execute(text(
                "SELECT id FROM bot_profiles WHERE name = :n"
            ), {"n": pname}).fetchone()
            actions.append({"table": "profile", "bot": pname,
                            "action": "created"})
            logger.warning("[m075] created bot_profile %s", pname)
        profile_id = int(prof[0])

        # Get or create bot_allocations row
        alloc = conn.execute(text(
            "SELECT id FROM bot_allocations WHERE user_id = :uid AND "
            "profile_id = :pid"
        ), {"uid": _BROCK_USER_ID, "pid": profile_id}).fetchone()
        if not alloc:
            conn.execute(text("""
                INSERT INTO bot_allocations
                  (user_id, profile_id, capital_pct, risk_profile,
                   paper_mode, enabled, starting_capital_cents,
                   tier, created_at, updated_at)
                VALUES
                  (:uid, :pid, 1.5, 'standard', 1, 1, :cap, 'T2', :ts, :ts)
            """), {
                "uid": _BROCK_USER_ID, "pid": profile_id,
                "cap": b["starting_capital_cents"], "ts": now_iso,
            })
            actions.append({"table": "alloc", "bot": pname,
                            "action": "created",
                            "cents": b["starting_capital_cents"]})
            logger.warning("[m075] created bot_allocation %s at %d cents",
                           pname, b["starting_capital_cents"])
        else:
            actions.append({"table": "alloc", "bot": pname,
                            "action": "already_exists"})

    # ── 5. Fund invariant check ──────────────────────────────────────────
    ba_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM portfolio_rank_bots"
    )).fetchone()
    fund_total = int(ba_row[0] or 0) + int(pr_row[0] or 0)

    if fund_total != 100_000_000:
        raise RuntimeError(
            f"m075 invariant broken: fund_total={fund_total} != 100000000 "
            f"(ba={ba_row[0]}, pr={pr_row[0]})"
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "actions": actions,
        "fund_total_cents": fund_total,
        "invariant_ok": True,
    }
