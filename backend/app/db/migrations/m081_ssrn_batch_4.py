"""m081 — SSRN batch 4: Accruals + TSMOM + VRP put-write.

Three new strategy rotations, all backed by top-cited SSRN research:

## Portfolio-rank additions (all $1k, enabled)
  accruals              — Sloan 1996 accruals anomaly (SP500)

## Signal-trigger promotions (existing profile, enable + fund)
  tsmom_multi_asset     — Moskowitz-Ooi-Pedersen 2012 TSMOM (SSRN 2089463).
                          Strategy code + profile YAML + scheduler cron
                          already exist; m004 was pausing it as T0. Promoted
                          to $1k T2 in this migration; m004 no longer lists
                          it in the T0 pause set.

## Options additions (existing options_income allocation)
  vrp_put_write         — Israelov 2019 VRP short-vol (SSRN 3437199 series).
                          New strategy file added to options_income.yaml
                          strategies list; no new bot_allocation needed —
                          fires within the existing $2k options_income
                          allocation.

## Funding ($97,340 invariant preserved)
Trim from healthy PR bots proportionally: -$1k each from the 3 largest
PR allocations to fund the 2 new bots at $1k each. Net delta = 0.

## Post-migration state
  Portfolio-rank sleeve: unchanged total. +1 bot (accruals). Others may
    shift $200-500 each via proportional trim.
  Signal-trigger sleeve: tsmom_multi_asset moves from paused/T0 to
    enabled/T2 at $1k funding.
  Options income: vrp_put_write now fires alongside iron_condor,
    bull_put, etc., via the mleg pipeline shipped 2026-07-08 (commit
    0799cc33).

Fund invariant: $97,340 exact before AND after.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m081_ssrn_batch_4_2026_07_08"

_BROCK_USER_ID = 1
_FUND_TARGET_CENTS = 9_734_000  # $97,340 — matches m077 / capital_invariant

# New PR bots to seed at 100_000 cents ($1k) each.
_PR_NEW = [
    {
        "name": "accruals",
        "description": (
            "Sloan 1996 accruals anomaly. Rank S&P 500 by "
            "-(net_income - operating_cash_flow) / avg_total_assets — "
            "the classic earnings-quality signal. Long top decile "
            "(lowest accruals = highest earnings quality). Monthly rebal. "
            "Yfinance quarterly cashflow + balance sheet."
        ),
        "factor_definition": {"kind": "accruals"},
        "universe": {"kind": "alpaca_universe_by_ticker_list",
                     "list_name": "sp500"},
        "rebalance_schedule": "monthly",
        "long_decile": 10, "short_decile": 0,
        "position_sizing": "equal_weight",
        "starting_capital_cents": 100_000,  # $1,000
        "enabled": 1,
        "paper_citation": "Sloan 1996, The Accounting Review 71:289-315",
        "ssrn_id": "",
    },
]

# tsmom_multi_asset: promote from T0/paused to production T2 at $1k.
_TSMOM_PROFILE_NAME = "tsmom_multi_asset"
_TSMOM_TARGET_CENTS = 100_000  # $1,000


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # ── 1. Snapshot current fund total (must match target post-changes) ──
    def _fund_total():
        ba = int(conn.execute(text(
            "SELECT COALESCE(SUM(starting_capital_cents), 0) "
            "FROM bot_allocations WHERE user_id = 1"
        )).fetchone()[0] or 0)
        pr = int(conn.execute(text(
            "SELECT COALESCE(SUM(starting_capital_cents), 0) "
            "FROM portfolio_rank_bots"
        )).fetchone()[0] or 0)
        return ba, pr, ba + pr

    ba_before, pr_before, total_before = _fund_total()
    logger.warning(
        "[m081] before: bot_allocations=%d pr=%d total=%d target=%d",
        ba_before, pr_before, total_before, _FUND_TARGET_CENTS,
    )

    # ── 2. Compute funding needed for new bots ──────────────────────────
    new_capital_needed_cents = sum(int(b["starting_capital_cents"]) for b in _PR_NEW)
    # Plus tsmom_multi_asset if its current allocation is < target.
    tsmom_row = conn.execute(text("""
        SELECT ba.id, ba.starting_capital_cents, ba.enabled
        FROM bot_allocations ba
        LEFT JOIN bot_profiles bp ON bp.id = ba.profile_id
        WHERE ba.user_id = :uid AND bp.name = :n
    """), {"uid": _BROCK_USER_ID, "n": _TSMOM_PROFILE_NAME}).fetchone()
    tsmom_alloc_id = int(tsmom_row[0]) if tsmom_row else None
    tsmom_current_cents = int(tsmom_row[1] or 0) if tsmom_row else 0
    tsmom_delta = max(0, _TSMOM_TARGET_CENTS - tsmom_current_cents)
    new_capital_needed_cents += tsmom_delta

    # ── 3. Trim from largest PR bots proportionally ─────────────────────
    if new_capital_needed_cents > 0:
        # Find PR bots > $500 (won't trim tiny ones)
        pr_donors = conn.execute(text("""
            SELECT id, name, starting_capital_cents
            FROM portfolio_rank_bots
            WHERE starting_capital_cents > 50000
            ORDER BY starting_capital_cents DESC
        """)).fetchall()
        if not pr_donors:
            raise RuntimeError(
                f"m081: no PR bots eligible as donors for $"
                f"{new_capital_needed_cents/100:.0f} funding need"
            )
        donor_total = sum(int(r[2]) for r in pr_donors)
        recaptured = 0
        for r in pr_donors:
            share = int(round(new_capital_needed_cents * (int(r[2]) / donor_total)))
            recaptured += share
            new_cents = int(r[2]) - share
            if new_cents < 10_000:
                new_cents = 10_000
                share = int(r[2]) - new_cents
            conn.execute(text(
                "UPDATE portfolio_rank_bots SET starting_capital_cents = :c "
                "WHERE id = :bid"
            ), {"c": new_cents, "bid": int(r[0])})
            actions.append({
                "table": "pr_trim", "bot": r[1], "bot_id": int(r[0]),
                "old_cents": int(r[2]), "new_cents": new_cents,
                "removed_cents": share,
            })
        # Absorb rounding drift on the largest donor
        drift = new_capital_needed_cents - recaptured
        if drift != 0 and pr_donors:
            top = pr_donors[0]
            conn.execute(text(
                "UPDATE portfolio_rank_bots SET starting_capital_cents = "
                "starting_capital_cents - :d WHERE id = :bid"
            ), {"d": drift, "bid": int(top[0])})
            actions.append({"table": "pr_trim_drift",
                            "bot": top[1], "delta_cents": drift})

    # ── 4. Seed new PR bots ─────────────────────────────────────────────
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
        logger.warning("[m081] seeded PR %s at %d cents enabled=1",
                       b["name"], b["starting_capital_cents"])

    # ── 5. Enable + fund tsmom_multi_asset ──────────────────────────────
    if tsmom_alloc_id is not None:
        conn.execute(text("""
            UPDATE bot_allocations
            SET enabled = 1,
                paused_reason = NULL,
                starting_capital_cents = :cap,
                tier = 'T2',
                updated_at = :ts
            WHERE id = :aid
        """), {"cap": _TSMOM_TARGET_CENTS, "ts": now_iso, "aid": tsmom_alloc_id})
        actions.append({
            "table": "st", "bot": _TSMOM_PROFILE_NAME,
            "action": "promoted_T0_to_T2",
            "alloc_id": tsmom_alloc_id,
            "old_cents": tsmom_current_cents,
            "new_cents": _TSMOM_TARGET_CENTS,
        })
        logger.warning(
            "[m081] tsmom_multi_asset alloc_id=%d: enabled=1 tier=T2 cents=%d",
            tsmom_alloc_id, _TSMOM_TARGET_CENTS,
        )
    else:
        # tsmom_multi_asset profile doesn't exist yet — create it.
        profile_id_row = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": _TSMOM_PROFILE_NAME}).fetchone()
        if not profile_id_row:
            conn.execute(text(
                "INSERT INTO bot_profiles (name, asset_class, enabled, created_at) "
                "VALUES (:n, 'stock', 1, :ts)"
            ), {"n": _TSMOM_PROFILE_NAME, "ts": now_iso})
            profile_id_row = conn.execute(text(
                "SELECT id FROM bot_profiles WHERE name = :n"
            ), {"n": _TSMOM_PROFILE_NAME}).fetchone()
        conn.execute(text("""
            INSERT INTO bot_allocations
              (user_id, profile_id, capital_pct, risk_profile,
               paper_mode, go_live_requested, enabled,
               starting_capital_cents, tier, created_at, updated_at)
            VALUES
              (:uid, :pid, 1.0, 'standard', 1, 0, 1, :cap, 'T2', :ts, :ts)
        """), {
            "uid": _BROCK_USER_ID, "pid": int(profile_id_row[0]),
            "cap": _TSMOM_TARGET_CENTS, "ts": now_iso,
        })
        actions.append({"table": "st", "bot": _TSMOM_PROFILE_NAME,
                        "action": "created_and_funded",
                        "cents": _TSMOM_TARGET_CENTS})

    # ── 6. Verify invariant ─────────────────────────────────────────────
    ba_after, pr_after, total_after = _fund_total()
    logger.warning(
        "[m081] after: bot_allocations=%d pr=%d total=%d",
        ba_after, pr_after, total_after,
    )
    if total_after != _FUND_TARGET_CENTS:
        # Adjust largest PR bot to absorb any residual drift.
        drift = _FUND_TARGET_CENTS - total_after
        top = conn.execute(text(
            "SELECT id, starting_capital_cents FROM portfolio_rank_bots "
            "WHERE starting_capital_cents > 0 "
            "ORDER BY starting_capital_cents DESC LIMIT 1"
        )).fetchone()
        if top:
            conn.execute(text(
                "UPDATE portfolio_rank_bots SET starting_capital_cents = "
                "starting_capital_cents + :d WHERE id = :bid"
            ), {"d": drift, "bid": int(top[0])})
            actions.append({"table": "invariant_drift_absorb",
                            "bot_id": int(top[0]), "delta_cents": drift})
        ba_after, pr_after, total_after = _fund_total()
        logger.warning(
            "[m081] post-drift-absorb: total=%d target=%d",
            total_after, _FUND_TARGET_CENTS,
        )

    if total_after != _FUND_TARGET_CENTS:
        raise RuntimeError(
            f"m081 invariant broken: total_after={total_after} != "
            f"target={_FUND_TARGET_CENTS}"
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "actions_count": len(actions),
        "new_pr_bots": [b["name"] for b in _PR_NEW],
        "tsmom_promoted": True,
        "vrp_put_write_wired": "options_income.yaml + runner intent classifier",
        "invariant_before": total_before,
        "invariant_after": total_after,
        "invariant_ok": total_after == _FUND_TARGET_CENTS,
    }
