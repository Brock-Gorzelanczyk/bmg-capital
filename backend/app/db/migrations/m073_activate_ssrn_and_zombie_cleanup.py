"""m073 — Activate 3 SSRN factor bots + clean 2 zombie rows.

From the 2026-07-06 full Strategy Lab audit. Two problems surfaced:

## Problem 1: 3 SSRN factor bots enabled but at $0 capital

m069 seeded low_volatility, value_hml, net_stock_issuance at $0.
m070 flipped enabled=1 so their crons would fire — but the funding
half of the plan was never written. Result: crons rebalance an empty
portfolio, no positions ever open. That contradicts Brock's "get
every strategy in the app trading" directive.

Fix: trim momentum_umd 50k → 35k and quality_gross_profitability
50k → 35k, freeing $30k. Allocate $10k to each of the three SSRN
bots. Cash_floor untouched.

## Problem 2: crypto_onchain zombie row

m061 drained crypto_onchain's capital to $0 and reallocated. The
row was left in bot_allocations with alloc_enabled=true. Cron still
fires with $0 to trade — wasteful scheduler ticks + strategy
scanning for nothing.

Fix: set enabled=0. Row kept for audit history.

## Problem 3: dummy_alpha_rank still enabled

Phase 1 framework verifier. Has no economic content (ranks S&P 500
subset alphabetically). Was rebalancing this morning at $0 → burns
yfinance quota. Turn off.

Fix: set enabled=0. Row kept for audit history.

## Post-migration state

  bot_allocations user_id=1:  $900,000 (unchanged) across 26 enabled
    minus crypto_onchain still-technically-enabled zombie now off
  portfolio_rank_bots:        $100,000 across 5 enabled + 3 dormant
    - momentum_umd                       $35,000
    - quality_gross_profitability        $35,000
    - low_volatility                     $10,000
    - value_hml                          $10,000
    - net_stock_issuance                 $10,000
    - dummy_alpha_rank            $0 disabled
    - idio_volatility             $0 disabled (m072 gap-filler)
    - tsm_12m                     $0 disabled (m072 gap-filler)

## Fund invariant

$1,000,000 exact before and after.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m073_activate_ssrn_and_zombie_cleanup_2026_07"


# Trims: current → new (cents)
_TRIMS = [
    ("momentum_umd", 5_000_000, 3_500_000),
    ("quality_gross_profitability", 5_000_000, 3_500_000),
]

# Fund up: current → new (cents)
_FUNDS = [
    ("low_volatility", 0, 1_000_000),
    ("value_hml", 0, 1_000_000),
    ("net_stock_issuance", 0, 1_000_000),
]

# Portfolio-rank bots to disable
_PR_DISABLE = ["dummy_alpha_rank"]

# Signal-trigger zombies (bot_allocations table)
_BA_DISABLE = ["crypto_onchain"]


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # ---- Pre-flight: verify current state matches expectations ----
    for name, expect, _new in _TRIMS:
        row = conn.execute(text(
            "SELECT starting_capital_cents, enabled "
            "FROM portfolio_rank_bots WHERE name = :n"
        ), {"n": name}).fetchone()
        if not row:
            raise RuntimeError(f"m073 pre-flight: {name} not found in portfolio_rank_bots")
        if int(row[0] or 0) != expect:
            raise RuntimeError(
                f"m073 pre-flight: {name} capital={row[0]} != expected {expect}"
            )
        if not bool(row[1]):
            raise RuntimeError(f"m073 pre-flight: {name} is disabled — refusing to trim")

    for name, expect, _new in _FUNDS:
        row = conn.execute(text(
            "SELECT starting_capital_cents, enabled "
            "FROM portfolio_rank_bots WHERE name = :n"
        ), {"n": name}).fetchone()
        if not row:
            raise RuntimeError(f"m073 pre-flight: {name} not found in portfolio_rank_bots")
        if int(row[0] or 0) != expect:
            raise RuntimeError(
                f"m073 pre-flight: {name} capital={row[0]} != expected {expect}"
            )

    # ---- 1. Trim momentum_umd + quality ----
    # Note: portfolio_rank_bots has no updated_at column (unlike bot_allocations).
    for name, _old, new in _TRIMS:
        conn.execute(text(
            "UPDATE portfolio_rank_bots "
            "SET starting_capital_cents = :c "
            "WHERE name = :n"
        ), {"c": new, "n": name})
        actions.append({"bot": name, "action": "trim", "new_cents": new})
        logger.warning("[m073] trimmed %s to %d cents", name, new)

    # ---- 2. Fund the 3 SSRN bots ----
    for name, _old, new in _FUNDS:
        conn.execute(text(
            "UPDATE portfolio_rank_bots "
            "SET starting_capital_cents = :c "
            "WHERE name = :n"
        ), {"c": new, "n": name})
        actions.append({"bot": name, "action": "fund", "new_cents": new})
        logger.warning("[m073] funded %s to %d cents", name, new)

    # ---- 3. Disable dummy_alpha_rank ----
    for name in _PR_DISABLE:
        res = conn.execute(text(
            "UPDATE portfolio_rank_bots SET enabled = 0 "
            "WHERE name = :n AND enabled = 1"
        ), {"n": name})
        actions.append({"bot": name, "action": "disable_pr", "rowcount": res.rowcount})
        logger.warning("[m073] disabled portfolio_rank_bot %s (rows=%d)", name, res.rowcount)

    # ---- 4. Disable crypto_onchain zombie in bot_allocations ----
    # bot_allocations uses profile_id FK — join through bot_profiles.
    for name in _BA_DISABLE:
        rows = conn.execute(text(
            "SELECT a.id, a.starting_capital_cents, a.enabled "
            "FROM bot_allocations a "
            "JOIN bot_profiles p ON p.id = a.profile_id "
            "WHERE a.user_id = 1 AND p.name = :n"
        ), {"n": name}).fetchall()
        if not rows:
            actions.append({"bot": name, "action": "disable_ba_not_found"})
            continue
        disabled_count = 0
        for r in rows:
            alloc_id = int(r[0])
            starting = int(r[1] or 0)
            was_enabled = bool(r[2])
            if not was_enabled:
                actions.append({"bot": name, "alloc_id": alloc_id, "action": "already_disabled"})
                continue
            if starting > 0:
                # Refuse to disable a funded bot without a fresh spec.
                actions.append({
                    "bot": name, "alloc_id": alloc_id,
                    "action": "skipped_has_capital",
                    "starting_cents": starting,
                })
                logger.warning(
                    "[m073] refusing to disable %s alloc_id=%d because capital=%d > 0",
                    name, alloc_id, starting,
                )
                continue
            conn.execute(text(
                "UPDATE bot_allocations SET enabled = 0, updated_at = :ts WHERE id = :aid"
            ), {"ts": now_iso, "aid": alloc_id})
            disabled_count += 1
            logger.warning("[m073] disabled zombie %s alloc_id=%d", name, alloc_id)
        actions.append({"bot": name, "action": "disable_ba", "disabled_count": disabled_count})

    # ---- Fund invariant check ----
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
            f"m073 invariant broken: fund_total={fund_total} != 100000000 "
            f"(ba={ba_row[0]}, pr={pr_row[0]})"
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "actions": actions,
        "fund_total_cents": fund_total,
        "invariant_ok": True,
    }
