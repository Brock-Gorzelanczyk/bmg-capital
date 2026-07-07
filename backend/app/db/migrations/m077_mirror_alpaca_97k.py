"""m077 — Mirror BMG fund invariant to Alpaca equity ($97,340) + re-enable options.

Per Brock 2026-07-07: "we can still use all of the bots and strategies and
bring the app to mirror alpaca at 97k"

Alpaca paper account equity: $97,340.09 (down $2,659.91 from $100k after
the credit-side sign-flip bug drained buying power via BUY-to-open iron
condors on options_income). Rather than reset Alpaca (would wipe the 3
legitimate crypto positions from last night's successful fills), we
proportionally rescale BMG's internal $1M fund down to $97,340. All bot
allocations shrink by factor 0.09734 (rounded to nearest cent per bot to
preserve exact invariant).

Also re-enables options_directional + options_income (halted by m076)
now that:
  - sell-side fix is deployed (b9a8f70f)
  - runner uses intent-based position side (488a3269)
  - options buying power unlocked to $88k via post-liquidation cleanup

Post-migration fleet:
  Signal-trigger sleeve: $87,606 (was $900,000)
  Portfolio-rank sleeve:  $9,734 (was $100,000)
  ─────────────────────────────
  Total:                  $97,340 == Alpaca equity ✓

Fund invariant target (used by capital_invariant.py) also updated in
same commit to 9,734,000 cents so watchdog stops CRIT-ing.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m077_mirror_alpaca_97k_2026_07_07"

# Alpaca equity at migration write time. Cents-precise.
_TARGET_TOTAL_CENTS = 9_734_000  # $97,340.00


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    actions: list[dict] = []

    # ── 1. Compute current totals ────────────────────────────────────────
    ba_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM portfolio_rank_bots"
    )).fetchone()
    current_ba = int(ba_row[0] or 0)
    current_pr = int(pr_row[0] or 0)
    current_total = current_ba + current_pr

    if current_total == 0:
        raise RuntimeError("m077: current fund total is 0, refusing to rescale")

    scale = _TARGET_TOTAL_CENTS / current_total
    logger.warning(
        "[m077] rescaling: current=%d cents, target=%d cents, factor=%.6f",
        current_total, _TARGET_TOTAL_CENTS, scale,
    )

    # ── 2. Rescale each bot_allocation individually so ratios preserved ──
    ba_rows = conn.execute(text("""
        SELECT id, starting_capital_cents FROM bot_allocations
        WHERE user_id = 1 AND starting_capital_cents > 0
        ORDER BY id
    """)).fetchall()

    ba_new_total = 0
    for row in ba_rows:
        alloc_id = int(row[0])
        old_cents = int(row[1])
        new_cents = int(round(old_cents * scale))
        if new_cents < 100:  # $1 min per bot
            new_cents = 100
        ba_new_total += new_cents
        conn.execute(text(
            "UPDATE bot_allocations SET starting_capital_cents = :c, "
            "updated_at = :ts WHERE id = :aid"
        ), {"c": new_cents, "ts": now_iso, "aid": alloc_id})
        actions.append({
            "table": "bot_allocations", "alloc_id": alloc_id,
            "old_cents": old_cents, "new_cents": new_cents,
        })

    # ── 3. Rescale each portfolio_rank_bot ──────────────────────────────
    pr_rows = conn.execute(text(
        "SELECT id, starting_capital_cents FROM portfolio_rank_bots "
        "WHERE starting_capital_cents > 0 ORDER BY id"
    )).fetchall()

    pr_new_total = 0
    for row in pr_rows:
        bot_id = int(row[0])
        old_cents = int(row[1])
        new_cents = int(round(old_cents * scale))
        if new_cents < 100:
            new_cents = 100
        pr_new_total += new_cents
        conn.execute(text(
            "UPDATE portfolio_rank_bots SET starting_capital_cents = :c "
            "WHERE id = :bid"
        ), {"c": new_cents, "bid": bot_id})
        actions.append({
            "table": "portfolio_rank_bots", "bot_id": bot_id,
            "old_cents": old_cents, "new_cents": new_cents,
        })

    # ── 4. Correct rounding drift to hit exact target ────────────────────
    # Sum the actual new totals and adjust the largest bot to make it match
    # EXACTLY. Rounding usually creates <20 cent drift; we absorb it in the
    # biggest bot which won't notice a few cents.
    total_after = ba_new_total + pr_new_total
    drift = _TARGET_TOTAL_CENTS - total_after
    if drift != 0:
        # Find the largest bot_allocation and apply drift there
        top = conn.execute(text(
            "SELECT id, starting_capital_cents FROM bot_allocations "
            "WHERE user_id = 1 ORDER BY starting_capital_cents DESC LIMIT 1"
        )).fetchone()
        if top:
            adj_id = int(top[0])
            adj_new = int(top[1]) + drift
            conn.execute(text(
                "UPDATE bot_allocations SET starting_capital_cents = :c "
                "WHERE id = :aid"
            ), {"c": adj_new, "aid": adj_id})
            actions.append({
                "table": "drift_absorb", "alloc_id": adj_id,
                "drift_cents": drift, "final_cents": adj_new,
            })

    # ── 5. Re-enable options bots (halted by m076) ──────────────────────
    for name in ("options_income", "options_directional"):
        prof = conn.execute(text(
            "SELECT id FROM bot_profiles WHERE name = :n"
        ), {"n": name}).fetchone()
        if not prof:
            continue
        res = conn.execute(text("""
            UPDATE bot_allocations
            SET enabled = 1,
                paused_reason = NULL,
                updated_at = :ts
            WHERE user_id = 1 AND profile_id = :pid AND enabled = 0
        """), {"ts": now_iso, "pid": int(prof[0])})
        actions.append({
            "table": "reenable", "bot": name, "rows": res.rowcount,
        })
        logger.warning("[m077] re-enabled %s (rows=%d)", name, res.rowcount)

    # ── 6. Assert invariant matches new target ──────────────────────────
    ba_check = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = 1"
    )).fetchone()
    pr_check = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM portfolio_rank_bots"
    )).fetchone()
    final_total = int(ba_check[0] or 0) + int(pr_check[0] or 0)

    if final_total != _TARGET_TOTAL_CENTS:
        raise RuntimeError(
            f"m077 invariant broken: final_total={final_total} != "
            f"target={_TARGET_TOTAL_CENTS} (drift={final_total - _TARGET_TOTAL_CENTS})"
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "actions_count": len(actions),
        "scale_factor": round(scale, 6),
        "before_total_cents": current_total,
        "after_total_cents": final_total,
        "invariant_ok": True,
    }
