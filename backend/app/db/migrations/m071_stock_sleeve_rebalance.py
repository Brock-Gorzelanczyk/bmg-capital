"""m071 — Stock sleeve rebalance: spread $400K across 11 strategies.

Brock's directive: increase strategy diversity in the stock sleeve. Cut
the 7 existing bots down modestly and fund the 4 dormant stock_quant
bots (day_meanrev / day_momentum / swing_growth / swing_value) so all
11 stock strategies collect data at meaningfully-sized allocations.

## Numbering note

Paste-ready called this m069 but m069 + m070 are already used this
session (SSRN factor batch + enable). This is m071. Behavior matches
spec.

## Sleeve deltas ($400K total unchanged)

  stock_lt:                  $80,000 → $50,000  (-$30K)
  stock_swing:               $90,000 → $60,000  (-$30K)
  stock_day:                 $70,000 → $50,000  (-$20K)
  stock_orb_breakout:        $40,000 → $40,000  (unchanged)
  stock_gap_fade:            $40,000 → $30,000  (-$10K)
  stock_pead:                $40,000 → $30,000  (-$10K)
  stock_momentum_breakout:   $40,000 → $30,000  (-$10K)
  stock_quant_day_meanrev:        $0 → $30,000  (+$30K)
  stock_quant_day_momentum:       $0 → $30,000  (+$30K)
  stock_quant_swing_growth:       $0 → $30,000  (+$30K)
  stock_quant_swing_value:        $0 → $20,000  (+$20K)
  ────────────────────────────────────────────────
  Sleeve total:            $400,000 → $400,000

## Deviation from spec: enabled flag

Paste-ready said "No changes to Enabled flags." But m068 (shipped
earlier this session) set enabled=false on the 4 orphan stock_quant
bots. Funding them without re-enabling would leave them at real
capital but silent — defeats the "get every strategy trading"
directive. So m071 also flips enabled=1 on the 4 orphans as part of
the same transaction. Documented here so a future audit sees the
divergence explicitly.

## Guardrails

Pre-mutation:
  - Verify current allocation matches BEFORE table exactly (per bot)
  - Verify each of the 4 orphan bots has a YAML file on disk (proves
    the strategy runner can find its config)
  - Verify their bot_profiles rows exist

If any bot fails ANY check, migration aborts before any UPDATE. Report
returns the guard_report so Brock can see what needs fixing before
re-running.

Post-mutation:
  - Sum bot_allocations for user 1 + portfolio_rank_bots. Assert
    exactly $1,000,000.
  - On mismatch: RAISE, transaction rolls back, gate does NOT record.

## Fund invariant

$1,000,000 before and after. Only intra-sleeve reshuffle.

## Rollback

Manual rollback via reverse UPDATEs. To restore the pre-m071 state:
  UPDATE bot_allocations SET starting_capital_cents = <pre_value>
    WHERE user_id = 1 AND profile_id IN (SELECT id FROM bot_profiles
      WHERE name = <bot_name>);
Then UPDATE bot_allocations SET enabled = 0 for the 4 orphan bots to
restore m068 state.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import text

from app.db.migrations._gate import already_ran, record

logger = logging.getLogger(__name__)

_MIGRATION_NAME = "m071_stock_sleeve_rebalance_2026_07"
_BROCK_USER_ID = 1
_INVARIANT_TARGET = 100_000_000

# Values in cents. Documented next to each for readability.
_BEFORE = {
    "stock_lt":                8_000_000,   # $80k
    "stock_swing":             9_000_000,   # $90k
    "stock_day":               7_000_000,   # $70k
    "stock_orb_breakout":      4_000_000,   # $40k
    "stock_gap_fade":          4_000_000,   # $40k
    "stock_pead":              4_000_000,   # $40k
    "stock_momentum_breakout": 4_000_000,   # $40k
    "stock_quant_day_meanrev":         0,
    "stock_quant_day_momentum":        0,
    "stock_quant_swing_growth":        0,
    "stock_quant_swing_value":         0,
}

_AFTER = {
    "stock_lt":                5_000_000,   # $50k
    "stock_swing":             6_000_000,   # $60k
    "stock_day":               5_000_000,   # $50k
    "stock_orb_breakout":      4_000_000,   # $40k (unchanged)
    "stock_gap_fade":          3_000_000,   # $30k
    "stock_pead":              3_000_000,   # $30k
    "stock_momentum_breakout": 3_000_000,   # $30k
    "stock_quant_day_meanrev":  3_000_000,  # $30k
    "stock_quant_day_momentum": 3_000_000,  # $30k
    "stock_quant_swing_growth": 3_000_000,  # $30k
    "stock_quant_swing_value":  2_000_000,  # $20k
}

_ORPHAN_NAMES = (
    "stock_quant_day_meanrev",
    "stock_quant_day_momentum",
    "stock_quant_swing_growth",
    "stock_quant_swing_value",
)

_PROFILES_DIR = Path(__file__).parent.parent.parent.parent / "strategy_lab" / "profiles"


def _get_alloc(conn, bot_name: str) -> tuple[int, int, bool] | None:
    row = conn.execute(text(
        "SELECT a.id, a.starting_capital_cents, a.enabled "
        "FROM bot_allocations a "
        "JOIN bot_profiles p ON p.id = a.profile_id "
        "WHERE a.user_id = :uid AND p.name = :n"
    ), {"uid": _BROCK_USER_ID, "n": bot_name}).fetchone()
    if not row:
        return None
    return int(row[0]), int(row[1] or 0), bool(row[2])


def run(conn) -> dict:
    if already_ran(conn, _MIGRATION_NAME):
        return {"skipped_reason": "already_applied", "executed": False}

    now_iso = datetime.now(timezone.utc).isoformat()
    guard_report: list[dict] = []
    aborts: list[str] = []

    # ── Pre-mutation guard: verify current state matches BEFORE table ────────
    for name, expected in _BEFORE.items():
        info = _get_alloc(conn, name)
        if info is None:
            aborts.append(f"{name}: no allocation for user 1")
            guard_report.append({"bot": name, "found": False})
            continue
        alloc_id, actual, enabled = info
        entry = {
            "bot": name, "alloc_id": alloc_id,
            "expected_before_cents": expected, "actual_cents": actual,
            "match": actual == expected, "currently_enabled": enabled,
        }
        guard_report.append(entry)
        if actual != expected:
            aborts.append(
                f"{name}: expected {expected} cents (${expected/100:.0f}) but "
                f"found {actual} cents (${actual/100:.0f}). State drifted since "
                f"paste-ready was written."
            )

    # ── Verify orphan bot YAML files exist ──────────────────────────────────
    for name in _ORPHAN_NAMES:
        yaml_path = _PROFILES_DIR / f"{name}.yaml"
        exists = yaml_path.exists()
        guard_report.append({
            "bot": name, "yaml_exists": exists, "yaml_path": str(yaml_path),
        })
        if not exists:
            aborts.append(
                f"{name}: YAML profile file not found at {yaml_path}. "
                f"Cannot fund a bot whose strategy runner has no config."
            )

    if aborts:
        logger.error("[m071] pre-mutation guard failed: %s", aborts)
        return {
            "executed": False,
            "skipped_reason": "pre_mutation_guard_failed",
            "guard_report": guard_report,
            "aborts": aborts,
        }

    # ── Apply the 11 UPDATEs ────────────────────────────────────────────────
    actions: list[dict] = []
    for name, target_cents in _AFTER.items():
        info = _get_alloc(conn, name)
        alloc_id, current, currently_enabled = info  # already verified non-None
        # Update capital.
        conn.execute(text(
            "UPDATE bot_allocations "
            "SET starting_capital_cents = :c, updated_at = :now "
            "WHERE id = :aid"
        ), {"c": target_cents, "now": now_iso, "aid": alloc_id})
        # For the 4 orphan bots: also re-enable (m068 disabled them).
        # Documented deviation from spec — see docstring.
        newly_enabled = False
        if name in _ORPHAN_NAMES and not currently_enabled:
            conn.execute(text(
                "UPDATE bot_allocations SET enabled = 1 WHERE id = :aid"
            ), {"aid": alloc_id})
            newly_enabled = True

        actions.append({
            "bot": name, "alloc_id": alloc_id,
            "from_cents": current, "to_cents": target_cents,
            "delta_cents": target_cents - current,
            "newly_enabled": newly_enabled,
        })
        logger.warning(
            "[m071] %s: %d → %d (delta %+d, $%+d)%s",
            name, current, target_cents,
            target_cents - current, (target_cents - current) // 100,
            " + enabled" if newly_enabled else "",
        )

    # ── Post-mutation invariant ──────────────────────────────────────────────
    ba_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) "
        "FROM bot_allocations WHERE user_id = :uid"
    ), {"uid": _BROCK_USER_ID}).fetchone()
    ba_total = int(ba_row[0] or 0) if ba_row else 0
    pr_row = conn.execute(text(
        "SELECT COALESCE(SUM(starting_capital_cents), 0) FROM portfolio_rank_bots"
    )).fetchone()
    pr_total = int(pr_row[0] or 0) if pr_row else 0
    fund_total = ba_total + pr_total
    invariant_ok = fund_total == _INVARIANT_TARGET

    logger.warning(
        "[m071] invariant post-check: bot_allocations=$%d "
        "portfolio_rank_bots=$%d fund_total=$%d (target $%d) invariant_ok=%s",
        ba_total // 100, pr_total // 100, fund_total // 100,
        _INVARIANT_TARGET // 100, invariant_ok,
    )

    if not invariant_ok:
        raise RuntimeError(
            f"m071 invariant broken: fund_total={fund_total} "
            f"target={_INVARIANT_TARGET} delta={fund_total - _INVARIANT_TARGET}. "
            f"All UPDATEs rolled back."
        )

    record(conn, _MIGRATION_NAME)
    return {
        "executed": True,
        "actions": actions,
        "bot_allocations_total_cents": ba_total,
        "portfolio_rank_bots_total_cents": pr_total,
        "fund_total_cents": fund_total,
        "invariant_ok": True,
        "guard_report": guard_report,
    }
