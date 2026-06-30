"""Regression: all-time return must include unrealized P&L from open positions.

2026-06-30 incident: Stock Swing leaderboard showed 0.00% all-time return while
the bot detail page (computing from current_value) showed +0.15% on a $161
unrealized AMD position. Cause: SHIP 3's SUM(realized)/inception formula in
canonical.compute_bot_snapshot and the three router endpoints (leaderboard.py,
bots.py, allocation.py) silently dropped the unrealized P&L.

These tests assert the contract via static greps so the regression is impossible
without rewriting the contract simultaneously. Functional verification happens
end-to-end via the canonical snapshot path; pure unit-level mocking of the
canonical chain is blocked by conftest.py's app-package stub (the test suite's
deliberate fast-test isolation), so we lock the contract structurally.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def test_canonical_compute_bot_snapshot_uses_pv_minus_starting():
    """canonical.compute_bot_snapshot must compute all_time_return_pct from
    (portfolio_value_cents - starting_capital_cents) / starting_capital_cents.

    portfolio_value_cents already includes realized + unrealized (line 344
    invariant), so this formula captures open-position P&L. The realized-only
    SUM(bot_daily_pnl.realized_cents)/inception path is allowed only as a
    fallback when starting_capital_cents is zero.
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    # The primary calc must reference portfolio_value_cents and starting_capital_cents.
    pv_minus_starting = re.search(
        r"\(\s*portfolio_value_cents\s*-\s*starting_capital_cents\s*\)\s*/\s*starting_capital_cents",
        src,
    )
    assert pv_minus_starting is not None, (
        "canonical.compute_bot_snapshot must compute all_time_return_pct from "
        "(portfolio_value_cents - starting_capital_cents) / starting_capital_cents"
    )
    # The realized-only formula must not be the primary path.
    # Look for `all_time_return_pct = _pnl_based_pct` as the first assignment.
    primary_realized_only = re.search(
        r"^\s*all_time_return_pct\s*=\s*_pnl_based_pct\s*$",
        src,
        re.MULTILINE,
    )
    if primary_realized_only:
        # Must be inside an elif/else branch, not the primary path.
        before = src[: primary_realized_only.start()]
        last_elif = max(before.rfind("elif "), before.rfind("else:"))
        last_if = before.rfind("    if ")  # match the if at the same indent level
        assert last_elif > last_if, (
            "canonical.compute_bot_snapshot uses realized-only _pnl_based_pct as "
            "the primary all_time_return_pct path — regression of 2026-06-30 bug"
        )


def test_canonical_compute_portfolio_snapshot_uses_pv_minus_starting():
    """compute_portfolio_snapshot must also use (PV - starting) / starting so
    portfolio-level all-time includes child bots' unrealized P&L.
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    # Find the portfolio function and ensure its all-time block uses PV-minus-starting.
    # There are two places in canonical.py where this pattern should appear
    # (compute_bot_snapshot + compute_portfolio_snapshot) — assert both.
    matches = re.findall(
        r"\(\s*portfolio_value_cents\s*-\s*starting_capital_cents\s*\)\s*/\s*starting_capital_cents",
        src,
    )
    assert len(matches) >= 2, (
        f"canonical.py must compute all_time_return_pct from PV-minus-starting in "
        f"BOTH compute_bot_snapshot and compute_portfolio_snapshot — found {len(matches)}"
    )


def test_leaderboard_router_uses_snap_pv_formula():
    """leaderboard.py all_time_pnl_pct must come from snap.portfolio_value_cents,
    not from get_all_time_pct_with_meta["pct"] directly (which is realized-only).
    """
    src = (BACKEND / "app" / "routers" / "leaderboard.py").read_text()
    assert "snap.portfolio_value_cents" in src, (
        "leaderboard.py must use snap.portfolio_value_cents in the all-time formula"
    )
    # Regression check: `all_time_pnl_pct = _at_meta["pct"]` as the ONLY assignment
    # would mean realized-only is the primary path.
    primary_assign = re.search(
        r"^\s*all_time_pnl_pct\s*=\s*_at_meta\[\"pct\"\]\s*$",
        src,
        re.MULTILINE,
    )
    if primary_assign:
        before = src[: primary_assign.start()]
        last_else = before.rfind("else:")
        last_if = before.rfind("if ")
        assert last_else > last_if, (
            "leaderboard.py uses realized-only pct as primary — regression of "
            "2026-06-30 unrealized-P&L bug"
        )


def test_bots_router_uses_pv_formula():
    """bots.py detail endpoint must compute return_all_time_pct from
    (portfolio_value_cents - starting_capital) / starting_capital, not from the
    realized-only _at_meta_bot["pct"] field.
    """
    src = (BACKEND / "app" / "routers" / "bots.py").read_text()
    primary_realized_only = re.search(
        r"return_all_time_pct\s*=\s*_at_meta_bot\[\"pct\"\]\s*/\s*100",
        src,
    )
    assert primary_realized_only is None, (
        "bots.py uses realized-only _at_meta_bot[\"pct\"] for return_all_time_pct — "
        "regression of 2026-06-30 unrealized-P&L bug"
    )
    assert (
        "(portfolio_value_cents - starting_capital) / starting_capital" in src
    ), "bots.py must compute return_all_time_pct from (PV - starting) / starting"


def test_allocation_router_uses_canonical_snapshot():
    """allocation.py must use compute_bot_snapshot for all_time_pct so the value
    reflects open-position unrealized P&L (the nightly BotPerformanceStats
    rollup lags real-time and SHIP 3's get_all_time_pct was realized-only).
    """
    src = (BACKEND / "app" / "routers" / "allocation.py").read_text()
    assert "compute_bot_snapshot" in src, (
        "allocation.py must call compute_bot_snapshot so all_time_pct includes "
        "unrealized P&L from open positions"
    )
    assert "snap.portfolio_value_cents" in src, (
        "allocation.py must compute all_time_pct from snap.portfolio_value_cents"
    )


def test_pv_minus_starting_formula_documented_in_canonical_comment():
    """Trip-wire: the comment in canonical.py explaining the 2026-06-30 fix must
    remain so future readers understand WHY the (PV - starting) / starting
    formula is correct (and why SHIP 3's realized-only formula was wrong).
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    assert "2026-06-30" in src, (
        "canonical.py must retain the 2026-06-30 incident comment explaining "
        "why all_time_return_pct includes unrealized P&L"
    )
    assert "unrealized" in src.lower(), (
        "canonical.py comment must mention unrealized P&L inclusion"
    )
