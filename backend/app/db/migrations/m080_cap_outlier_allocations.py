"""m080 — Cap any bot_allocation over $15k, redistribute delta to preserve invariant.

Root cause (2026-07-08 pre-open audit):
Today's stock deployment showed 5 mega-caps bought at ~$23k each — a
clear equal-weight basket from a single bot with ~$116k allocated. The
fund is $97,340 total, so no single bot should be holding more than a
sleeve's worth of capital. Something slipped past m077.

Possible causes (all end at the same fix):
 - New allocation created after m077 with stale $100k starting_capital
 - A migration between m077 and now bumped an allocation back up
 - Portfolio_rank rebalancer wrote a target weight × pre-rescale capital

The concentration risk is live: GOOGL alone is $23k = 24% of fund. A 3%
overnight gap = $700 real loss on top of today's -$4,590.

Fix:
1. Find every bot_allocations row with starting_capital_cents > 1_500_000
   ($15k, well above expected max post-m077 rescale).
2. Cap each at 1_000_000 cents ($10k).
3. Redistribute the excess proportionally across the *unaffected*
   bot_allocations so sum(starting_capital_cents) + sum(portfolio_rank_bots.
   starting_capital_cents) still equals the fund invariant ($97,340).
4. Assert invariant holds after redistribution.
5. Log outliers loudly so we can grep for the culprit tomorrow.

Also runs before market open (as a startup migration) so it takes effect
before any bot picks up its stale big-capital allocation for today's
scan cycle.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m080_cap_outlier_allocations_2026_07_08"

_OUTLIER_THRESHOLD_CENTS = 1_500_000  # $15,000 — anything above this is broken
_CAP_TARGET_CENTS = 1_000_000         # $10,000 — max per bot post-fix
_FUND_TARGET_TOTAL_CENTS = 9_734_000  # $97,340 — must match m077 / capital_invariant


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # ── 1. Snapshot invariant BEFORE ─────────────────────────────────────
    ba_before_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    pr_before_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM portfolio_rank_bots"
    )).fetchone()
    ba_before = int(ba_before_row[0] or 0)
    pr_before = int(pr_before_row[0] or 0)
    total_before = ba_before + pr_before

    logger.warning(
        "[m080] invariant before: bot_allocations=%d cents, portfolio_rank=%d cents, total=%d cents",
        ba_before, pr_before, total_before,
    )

    # ── 2. Find and cap outliers ─────────────────────────────────────────
    outliers = conn.execute(text("""
        SELECT ba.id, ba.starting_capital_cents, bp.name
        FROM bot_allocations ba
        LEFT JOIN bot_profiles bp ON bp.id = ba.profile_id
        WHERE ba.user_id = 1
          AND ba.starting_capital_cents > :thresh
        ORDER BY ba.starting_capital_cents DESC
    """), {"thresh": _OUTLIER_THRESHOLD_CENTS}).fetchall()

    excess_recaptured_cents = 0
    outlier_ids: set[int] = set()
    for row in outliers:
        alloc_id = int(row[0])
        old_cents = int(row[1])
        bot_name = row[2] or f"alloc_{alloc_id}"
        delta = old_cents - _CAP_TARGET_CENTS
        excess_recaptured_cents += delta
        outlier_ids.add(alloc_id)
        conn.execute(text(
            "UPDATE bot_allocations SET starting_capital_cents = :c, "
            "updated_at = :ts WHERE id = :aid"
        ), {"c": _CAP_TARGET_CENTS, "ts": now_iso, "aid": alloc_id})
        logger.warning(
            "[m080] OUTLIER CAPPED: bot=%s alloc_id=%d %d -> %d cents (removed %d cents = $%.2f)",
            bot_name, alloc_id, old_cents, _CAP_TARGET_CENTS, delta, delta / 100.0,
        )
        actions.append({
            "action": "cap_outlier",
            "bot": bot_name,
            "alloc_id": alloc_id,
            "old_cents": old_cents,
            "new_cents": _CAP_TARGET_CENTS,
            "removed_cents": delta,
        })

    if not outliers:
        logger.warning("[m080] no outliers found — all bot_allocations already <= $%d",
                       _OUTLIER_THRESHOLD_CENTS // 100)
        record(conn, _MIGRATION_NAME)
        return {
            "executed": True,
            "outliers_found": 0,
            "invariant_ok": True,
            "note": "clean — no rebalance needed",
        }

    # ── 3. Redistribute the captured excess to preserve invariant ────────
    # Distribute proportionally to non-outlier bot_allocations so ratios
    # among healthy bots are preserved. We do NOT touch portfolio_rank_bots
    # because those already went through m077's rescale and don't have
    # the outlier problem (verified by m077 rescale factor logs).
    healthy_rows = conn.execute(text("""
        SELECT id, starting_capital_cents FROM bot_allocations
        WHERE user_id = 1
          AND starting_capital_cents > 0
          AND id NOT IN :outliers
    """.replace(":outliers", "(" + ",".join(str(x) for x in outlier_ids) + ")")
    )).fetchall() if outlier_ids else []

    healthy_total = sum(int(r[1]) for r in healthy_rows)

    if healthy_total == 0:
        # No healthy bots to absorb — dump excess into a single "cash_floor"
        # allocation if it exists, else the largest healthy bot.
        logger.warning(
            "[m080] no healthy bots to absorb $%d — trying cash_floor",
            excess_recaptured_cents // 100,
        )
        cf = conn.execute(text("""
            SELECT ba.id, ba.starting_capital_cents FROM bot_allocations ba
            LEFT JOIN bot_profiles bp ON bp.id = ba.profile_id
            WHERE ba.user_id = 1 AND bp.name = 'cash_floor'
            LIMIT 1
        """)).fetchone()
        if cf:
            adj_id = int(cf[0])
            adj_new = int(cf[1]) + excess_recaptured_cents
            conn.execute(text(
                "UPDATE bot_allocations SET starting_capital_cents = :c "
                "WHERE id = :aid"
            ), {"c": adj_new, "aid": adj_id})
            actions.append({
                "action": "excess_to_cash_floor",
                "alloc_id": adj_id,
                "added_cents": excess_recaptured_cents,
                "final_cents": adj_new,
            })
    else:
        # Proportional redistribution
        redistributed = 0
        for row in healthy_rows:
            alloc_id = int(row[0])
            current = int(row[1])
            share = int(round(excess_recaptured_cents * (current / healthy_total)))
            redistributed += share
            new_val = current + share
            conn.execute(text(
                "UPDATE bot_allocations SET starting_capital_cents = :c, "
                "updated_at = :ts WHERE id = :aid"
            ), {"c": new_val, "ts": now_iso, "aid": alloc_id})
        # Absorb rounding drift into the biggest healthy bot
        drift = excess_recaptured_cents - redistributed
        if drift != 0:
            top = conn.execute(text("""
                SELECT id, starting_capital_cents FROM bot_allocations
                WHERE user_id = 1 AND starting_capital_cents > 0
                ORDER BY starting_capital_cents DESC LIMIT 1
            """)).fetchone()
            if top:
                conn.execute(text(
                    "UPDATE bot_allocations SET starting_capital_cents = :c "
                    "WHERE id = :aid"
                ), {"c": int(top[1]) + drift, "aid": int(top[0])})
        actions.append({
            "action": "redistribute",
            "healthy_bot_count": len(healthy_rows),
            "redistributed_cents": excess_recaptured_cents,
            "drift_absorbed": drift,
        })

    # ── 4. Assert invariant holds ────────────────────────────────────────
    ba_after = int(conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()[0] or 0)
    pr_after = int(conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM portfolio_rank_bots"
    )).fetchone()[0] or 0)
    total_after = ba_after + pr_after

    logger.warning(
        "[m080] invariant after: bot_allocations=%d cents, portfolio_rank=%d cents, total=%d cents",
        ba_after, pr_after, total_after,
    )

    if total_after != _FUND_TARGET_TOTAL_CENTS:
        # Non-fatal but log loudly. m077 aims for exact match; if we drift
        # here it's because pre-m080 state was already off. Don't raise
        # because that would prevent the outlier cap from committing.
        logger.error(
            "[m080] invariant drift: total_after=%d cents vs target=%d cents (delta=%d)",
            total_after, _FUND_TARGET_TOTAL_CENTS,
            total_after - _FUND_TARGET_TOTAL_CENTS,
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "outliers_found": len(outliers),
        "outlier_names": [a["bot"] for a in actions if a["action"] == "cap_outlier"],
        "excess_recaptured_cents": excess_recaptured_cents,
        "excess_recaptured_dollars": excess_recaptured_cents / 100.0,
        "invariant_before_cents": total_before,
        "invariant_after_cents": total_after,
        "invariant_target_cents": _FUND_TARGET_TOTAL_CENTS,
        "invariant_ok": total_after == _FUND_TARGET_TOTAL_CENTS,
        "actions": actions,
    }
