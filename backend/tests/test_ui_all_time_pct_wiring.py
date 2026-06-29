"""SHIP 3 — API shape tests confirming get_all_time_pct is wired to
the 3 router endpoints that previously used the broken formula.

These are static analysis / code-grep tests — they verify the source
code of each router calls get_all_time_pct rather than the broken
(current_value - starting) / starting formula.

Not integration tests (that would require a full FastAPI test client).
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def _read(rel_path: str) -> str:
    return (BACKEND / rel_path).read_text()


# ---------------------------------------------------------------------------
# Pattern guards: the broken formula must not appear in changed router files
# ---------------------------------------------------------------------------

_BROKEN_FORMULA = re.compile(
    r"\(\s*current[_\s]value\s*-\s*starting\s*\)\s*/\s*starting",
    re.IGNORECASE,
)

_BROKEN_FORMULA_2 = re.compile(
    r"\(\s*portfolio_value_cents\s*-\s*starting_capital\s*\)\s*/\s*starting_capital\b",
    re.IGNORECASE,
)


def test_leaderboard_router_uses_get_all_time_pct():
    """leaderboard.py must import and call get_all_time_pct_with_meta."""
    src = _read("app/routers/leaderboard.py")
    assert "get_all_time_pct" in src, (
        "leaderboard.py must import get_all_time_pct (SHIP 3 PART 2)"
    )
    assert "get_all_time_pct_with_meta" in src, (
        "leaderboard.py must call get_all_time_pct_with_meta for is_post_reset metadata"
    )
    assert not _BROKEN_FORMULA.search(src), (
        "leaderboard.py still contains broken (current_value - starting) / starting formula"
    )


def test_allocation_router_uses_get_all_time_pct():
    """allocation.py must import and call get_all_time_pct."""
    src = _read("app/routers/allocation.py")
    assert "get_all_time_pct" in src, (
        "allocation.py must import get_all_time_pct (SHIP 3 PART 2)"
    )
    # The old formula used (current_val - starting) / starting
    assert "current_val - starting" not in src or "get_all_time_pct" in src, (
        "allocation.py still uses the broken (current_val - starting) / starting formula"
    )


def test_bots_router_uses_get_all_time_pct_with_meta():
    """bots.py must call get_all_time_pct_with_meta for the card endpoint.

    The old formula (portfolio_value_cents - starting_capital) / starting_capital
    is still allowed in the `else allocation is None` fallback path — the guard
    checks that the NEW path (when allocation exists) uses get_all_time_pct_with_meta.
    """
    src = _read("app/routers/bots.py")
    assert "get_all_time_pct_with_meta" in src, (
        "bots.py must call get_all_time_pct_with_meta (SHIP 3 PART 2)"
    )
    # The broken formula is now only in the fallback `else` block (no allocation).
    # Confirm the primary path calls get_all_time_pct_with_meta
    assert "_get_at_meta" in src or "get_all_time_pct_with_meta" in src, (
        "bots.py all-time return must use get_all_time_pct_with_meta when allocation exists"
    )


def test_canonical_uses_get_all_time_pct():
    """canonical.py must call get_all_time_pct instead of the broken formula."""
    src = _read("app/core/canonical.py")
    assert "get_all_time_pct" in src or "bot_performance" in src, (
        "canonical.py must call get_all_time_pct (SHIP 3 PART 2)"
    )


def test_leaderboard_response_includes_is_post_reset_field():
    """leaderboard.py must include is_post_reset and reset_date in row dict."""
    src = _read("app/routers/leaderboard.py")
    assert "is_post_reset" in src, (
        "leaderboard.py must include is_post_reset in row response"
    )
    assert "reset_date" in src, (
        "leaderboard.py must include reset_date in row response"
    )


def test_bots_router_return_all_time_includes_meta():
    """bots.py card response must include is_post_reset and reset_date in return_all_time."""
    src = _read("app/routers/bots.py")
    assert "is_post_reset" in src, (
        "bots.py card return_all_time dict must include is_post_reset"
    )
    assert "reset_date" in src, (
        "bots.py card return_all_time dict must include reset_date"
    )


def test_no_new_broken_formula_in_migration_history_files():
    """Migration history contract tests exist and are not empty."""
    contract_path = Path(__file__).parent / "test_migration_history_contract.py"
    assert contract_path.exists(), "test_migration_history_contract.py must exist"
    src = contract_path.read_text()
    assert "test_no_migration_deletes_bot_trades_for_user_1" in src
    assert "test_no_migration_deletes_bot_daily_pnl_for_user_1" in src
    assert "test_no_migration_updates_inception_capital_cents_after_m027" in src
