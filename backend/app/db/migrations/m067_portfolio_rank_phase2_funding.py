"""m067 — Portfolio-Rank Phase 2 funding (Option D).

Reallocates $100K to fund momentum_umd + quality_gross_profitability
by spreading a small trim across three existing bots. Brock's Option D:

  crypto_quant_aggressive:      $130,000 → $80,000   (frees $50K)
  options_directional:           $50,000 → $25,000   (frees $25K)
  options_income:                $50,000 → $25,000   (frees $25K)
  ─────────────────────────────────────────────────────────────────
  momentum_umd:                       $0 → $50,000   (funded)
  quality_gross_profitability:        $0 → $50,000   (funded)

Also enables both portfolio-rank bots so their scheduled rebalances
begin firing (dry-run only, gated by BMG_PORTFOLIO_RANK_LIVE_ORDERS).

Fund invariant: $1,000,000 exact, before and after.

## Guards

Pre-mutation: verifies each source bot's current allocation matches the
expected starting value. If any source drifted (someone changed
crypto_quant_aggressive since m061), the migration aborts before any
UPDATE runs. This prevents "silent overwrite" of a state the operator
may not have intended.

Post-mutation: sums bot_allocations + portfolio_rank_bots and asserts
= 100_000_000 cents. Logs invariant_ok in the return dict.

## Scope

Only touches user_id=1 (Brock). Perk (user_id=7) allocations are
untouched. Phase 2 pilot is Brock-only.

## Rollback

Idempotent via schema_migrations gate. To rollback: manually reverse
the five UPDATE statements. No destructive DDL.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m067_portfolio_rank_phase2_funding_2026_07"
_BROCK_USER_ID = 1
_INVARIANT_TARGET = 100_000_000  # $1,000,000 exact

# Expected pre-mutation state per m062. If any of these drift, abort.
_EXPECTED_SOURCE_STATE = {
    "crypto_quant_aggressive": 13_000_000,   # $130K
    "options_directional":      5_000_000,   # $50K
    "options_income":           5_000_000,   # $50K
}

# Target post-mutation state.
_TARGET_SOURCE_STATE = {
    "crypto_quant_aggressive":  8_000_000,   # $80K
    "options_directional":      2_500_000,   # $25K
    "options_income":           2_500_000,   # $25K
}

_TARGET_PORTFOLIO_RANK_STATE = {
    "momentum_umd":                 5_000_000,   # $50K
    "quality_gross_profitability":  5_000_000,   # $50K
}


def _get_bot_alloc(conn, bot_name: str, user_id: int):
    return conn.execute(text(
        "SELECT a.id, a.starting_capital_cents "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid AND p.name = :name"
    ), {"uid": user_id, "name": bot_name}).fetchone()


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    guard_report: list[dict] = []
    actions: list[dict] = []

    # ── Pre-mutation guard: verify source state matches expectation ─────────
    aborts: list[str] = []
    for bot_name, expected in _EXPECTED_SOURCE_STATE.items():
        row = _get_bot_alloc(conn, bot_name, _BROCK_USER_ID)
        if not row:
            aborts.append(f"{bot_name}: allocation not found for user {_BROCK_USER_ID}")
            guard_report.append({"bot": bot_name, "found": False})
            continue
        actual = int(row[1] or 0)
        guard_report.append({
            "bot": bot_name, "alloc_id": int(row[0]),
            "expected_cents": expected, "actual_cents": actual,
            "match": actual == expected,
        })
        if actual != expected:
            aborts.append(
                f"{bot_name}: expected {expected} cents (${expected/100:.2f}) "
                f"but found {actual} cents (${actual/100:.2f}). "
                f"Someone changed this allocation since m061; migration "
                f"aborted to avoid overwriting an intentional change."
            )

    if aborts:
        logger.error("[m067] pre-mutation guard failed: %s", aborts)
        return {
            "executed": False,
            "skipped_reason": "pre_mutation_guard_failed",
            "guard_report": guard_report,
            "aborts": aborts,
        }

    # ── Verify portfolio-rank targets exist ─────────────────────────────────
    for pr_name in _TARGET_PORTFOLIO_RANK_STATE:
        pr_row = conn.execute(text(
            "SELECT id, starting_capital_cents FROM portfolio_rank_bots "
            "WHERE name = :n"
        ), {"n": pr_name}).fetchone()
        if not pr_row:
            aborts.append(
                f"{pr_name}: portfolio_rank_bots row not found. "
                f"Run m066 first."
            )
        else:
            guard_report.append({
                "bot": pr_name, "type": "portfolio_rank",
                "pr_id": int(pr_row[0]),
                "current_cents": int(pr_row[1] or 0),
            })
    if aborts:
        return {
            "executed": False,
            "skipped_reason": "portfolio_rank_target_missing",
            "guard_report": guard_report,
            "aborts": aborts,
        }

    # ── Trim the three source bots ──────────────────────────────────────────
    for bot_name, target_cents in _TARGET_SOURCE_STATE.items():
        row = _get_bot_alloc(conn, bot_name, _BROCK_USER_ID)
        alloc_id = int(row[0])
        current = int(row[1] or 0)
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET starting_capital_cents = :c, updated_at = :now "
            "WHERE id = :aid"
        ), {"c": target_cents, "now": now_iso, "aid": alloc_id})
        actions.append({
            "bot": bot_name,
            "table": "bot_allocations",
            "alloc_id": alloc_id,
            "from_cents": current,
            "to_cents": target_cents,
            "delta_cents": target_cents - current,
        })
        logger.warning(
            "[m067] %s: %d → %d (delta %+d, $%+d)",
            bot_name, current, target_cents,
            target_cents - current, (target_cents - current) // 100,
        )

    # ── Fund the two portfolio-rank bots ────────────────────────────────────
    for pr_name, target_cents in _TARGET_PORTFOLIO_RANK_STATE.items():
        current_row = conn.execute(text(
            "SELECT starting_capital_cents FROM portfolio_rank_bots "
            "WHERE name = :n"
        ), {"n": pr_name}).fetchone()
        current = int(current_row[0] or 0) if current_row else 0
        conn.execute(text(
            "UPDATE portfolio_rank_bots "
            "SET starting_capital_cents = :c, enabled = 1 "
            "WHERE name = :n"
        ), {"c": target_cents, "n": pr_name})
        actions.append({
            "bot": pr_name,
            "table": "portfolio_rank_bots",
            "from_cents": current,
            "to_cents": target_cents,
            "delta_cents": target_cents - current,
            "enabled": True,
        })
        logger.warning(
            "[m067] %s: %d → %d (delta %+d, $%+d), enabled=1",
            pr_name, current, target_cents,
            target_cents - current, (target_cents - current) // 100,
        )

    # ── Post-mutation invariant check ───────────────────────────────────────
    ba_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": _BROCK_USER_ID}).fetchone()
    ba_total = int(ba_row[0] or 0) if ba_row else 0

    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM portfolio_rank_bots"
    )).fetchone()
    pr_total = int(pr_row[0] or 0) if pr_row else 0

    fund_total = ba_total + pr_total
    invariant_ok = fund_total == _INVARIANT_TARGET

    logger.warning(
        "[m067] invariant post-check: bot_allocations=$%d "
        "portfolio_rank_bots=$%d fund_total=$%d (target $%d) invariant_ok=%s",
        ba_total // 100, pr_total // 100, fund_total // 100,
        _INVARIANT_TARGET // 100, invariant_ok,
    )

    if not invariant_ok:
        logger.error(
            "[m067] INVARIANT BROKEN: fund_total=%d != target=%d (delta %+d) — "
            "raising to trigger transaction rollback",
            fund_total, _INVARIANT_TARGET, fund_total - _INVARIANT_TARGET,
        )
        # Raise so the outer `with engine.begin()` in main.py rolls back
        # every UPDATE this migration issued. Without this raise, the
        # broken state would commit and the migration gate would record,
        # locking us out of a clean retry.
        raise RuntimeError(
            f"m067 invariant broken: fund_total={fund_total} "
            f"target={_INVARIANT_TARGET} delta={fund_total - _INVARIANT_TARGET}. "
            f"All UPDATEs rolled back."
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "bot_allocations_total_cents": ba_total,
        "portfolio_rank_bots_total_cents": pr_total,
        "fund_total_cents": fund_total,
        "invariant_ok": True,
        "guard_report": guard_report,
        "actions": actions,
    }
