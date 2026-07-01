"""Regression: /api/strategy-lab/portfolio leaderboard must include orphan
allocations (bots not bound to any StrategyPortfolio row — e.g. cash_floor).

2026-06-30 evening incident: Brock's homepage /strategy showed Portfolio Value
$898,541 instead of the true $1,000,000 (or $998,565 net today). Root cause:
compute_strategy_lab_aggregate built its leaderboard by iterating
portfolio_snapshots[*].bots, which only includes allocations bound to a
StrategyPortfolio row. cash_floor has no portfolio_id binding, so its $100k
allocation was silently dropped from the leaderboard, and the frontend's
"fallback = sum of sleeves/leaderboard" logic (which triggers when
labAggregate returns 0 on any API hiccup) undercounted by $100k.

Fix: after iterating portfolio_snapshots, also append any allocation whose
id wasn't already added. Uses the compute_bot_snapshot result if available,
otherwise falls back to a stub built from starting_capital.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def test_leaderboard_appends_orphan_allocations():
    """compute_strategy_lab_aggregate must include a follow-up loop over
    all_allocs that appends any allocation not already accounted for by
    portfolio_snapshots. Without this, orphan bots (cash_floor) are dropped.
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    # Locate compute_strategy_lab_aggregate
    fn_start = src.find("def compute_strategy_lab_aggregate(")
    assert fn_start > 0, "compute_strategy_lab_aggregate not found"
    fn_end = src.find("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end]

    # Must track which alloc ids have been added to the leaderboard.
    assert "seen_alloc_ids" in fn_body, (
        "compute_strategy_lab_aggregate must track seen_alloc_ids so orphan "
        "allocations (cash_floor) get appended after the portfolio-snapshot loop"
    )
    # Must have a follow-up loop over all_allocs after portfolio_snapshots.
    orphan_loop = re.search(
        r"for a in all_allocs:\s*\n\s*if a\.id in seen_alloc_ids:\s*\n\s*continue",
        fn_body,
    )
    assert orphan_loop is not None, (
        "compute_strategy_lab_aggregate must iterate all_allocs and skip already-"
        "seen alloc ids to append orphan bots (cash_floor) to the leaderboard. "
        "Regression of 2026-06-30 evening fix."
    )


def test_orphan_leaderboard_entry_has_starting_capital():
    """The stub built for orphan allocations without a snapshot must set
    starting_capital_cents (so the row shows a real dollar amount) and
    portfolio_value_cents (so the sleeve-sum fallback is accurate).
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    fn_start = src.find("def compute_strategy_lab_aggregate(")
    fn_end = src.find("\ndef ", fn_start + 1)
    fn_body = src[fn_start:fn_end]
    # Locate the orphan loop's else branch (the stub built without a snapshot)
    else_block_start = re.search(r"for a in all_allocs:.*?else:", fn_body, re.DOTALL)
    assert else_block_start is not None, "Could not locate orphan-stub else branch"
    else_block = fn_body[else_block_start.end():]
    # Must include starting_capital_cents in the stub.
    assert '"starting_capital_cents"' in else_block, (
        "Orphan-stub leaderboard entry must include starting_capital_cents so "
        "the row displays the correct allocation size"
    )
    # And portfolio_value_cents (defaulting to starting when no snapshot).
    assert '"portfolio_value_cents"' in else_block, (
        "Orphan-stub leaderboard entry must include portfolio_value_cents so "
        "the sleeve-sum fallback in the frontend adds up to the true fund total"
    )
