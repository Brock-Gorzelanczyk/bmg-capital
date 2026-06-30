"""Regression: /strategy homepage leaderboard parity with /strategy/leaderboard.

2026-06-30 split-brain bug: PR #53 fixed (PV - starting)/starting in
canonical.compute_bot_snapshot + 3 router endpoints (leaderboard, bots,
allocation). The dedicated /strategy/leaderboard surface read the corrected
snapshot.all_time_return_pct, but compute_strategy_lab_aggregate's leaderboard
list (consumed by the /strategy HOMEPAGE) emitted only return_30d_pct and
omitted all_time_return_pct — so the homepage continued to show 0.00% for
bots with no 30d realized fills even when their unrealized P&L was non-zero.

These tests lock the contract that every per-bot row in
compute_strategy_lab_aggregate()['leaderboard'] includes all_time_return_pct,
sorts by it, and uses Options/* not Equity/* display names.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def test_leaderboard_entries_include_all_time_return_pct():
    """compute_strategy_lab_aggregate's leaderboard rows must carry the
    all_time_return_pct field so the homepage surface gets the same number
    as the dedicated /strategy/leaderboard.
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    # Find the leaderboard.append({...}) block inside compute_strategy_lab_aggregate
    # and ensure all_time_return_pct is among the keys.
    leaderboard_block = re.search(
        r"leaderboard\.append\(\s*\{(.*?)\}\s*\)",
        src,
        re.DOTALL,
    )
    assert leaderboard_block is not None, (
        "Could not locate leaderboard.append({...}) block in canonical.py"
    )
    body = leaderboard_block.group(1)
    assert '"all_time_return_pct"' in body, (
        "compute_strategy_lab_aggregate leaderboard entries must include "
        "all_time_return_pct so the homepage matches /strategy/leaderboard"
    )
    # And the value must reference bot.all_time_return_pct (the snapshot field).
    assert "bot.all_time_return_pct" in body, (
        "all_time_return_pct must be sourced from bot.all_time_return_pct on "
        "the canonical BotSnapshot, not recomputed"
    )


def test_leaderboard_sorts_by_all_time_return_pct():
    """The homepage leaderboard must rank by all_time_return_pct first so the
    winner (positive all-time) ranks #1 and the bleeders (negative) rank last.
    Previously it sorted by return_30d_pct which buried positive-unrealized bots.
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    # Find the leaderboard.sort(key=...) call inside compute_strategy_lab_aggregate
    sort_block = re.search(
        r"leaderboard\.sort\(\s*key=lambda x:\s*\((.*?)\),\s*reverse=True",
        src,
        re.DOTALL,
    )
    assert sort_block is not None, (
        "Could not locate leaderboard.sort(...) in canonical.py"
    )
    keys = sort_block.group(1)
    # all_time_return_pct must be the FIRST sort key (highest priority).
    first_key = keys.split(",")[0].strip()
    assert "all_time_return_pct" in first_key, (
        f"Leaderboard must sort by all_time_return_pct FIRST; got first key {first_key!r}"
    )


def test_options_bots_show_options_display_name_not_equity():
    """The canonical DISPLAY_NAMES dict must label options_income and
    options_directional as 'Options *' not 'Equity *'. The legacy 'Equity'
    labels caused user confusion on the homepage (looked like phantom equity
    bots) while the dedicated leaderboard used the correct names.
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    # Must NOT contain the old Equity Income/Directional in the DISPLAY_NAMES dict.
    assert '"options_income":               "Equity Income"' not in src, (
        "canonical.py DISPLAY_NAMES still labels options_income as 'Equity Income'"
    )
    assert '"options_directional":          "Equity Directional"' not in src, (
        "canonical.py DISPLAY_NAMES still labels options_directional as 'Equity Directional'"
    )
    # Must contain the corrected names.
    assert '"Options Income"' in src, (
        "canonical.py DISPLAY_NAMES must use 'Options Income' for options_income"
    )
    assert '"Options Directional"' in src, (
        "canonical.py DISPLAY_NAMES must use 'Options Directional' for options_directional"
    )


def test_best_worst_performer_expose_all_time_return_pct():
    """The aggregate response's best_performer / worst_performer summaries must
    include all_time_return_pct so downstream surfaces (homepage hero card, AQA)
    can display the same number as the per-bot rows.
    """
    src = (BACKEND / "app" / "core" / "canonical.py").read_text()
    # Find the return statement near best_performer / worst_performer fields.
    bp_block = re.search(
        r'"best_performer":\s*\{(.*?)\}\s*if best',
        src,
        re.DOTALL,
    )
    wp_block = re.search(
        r'"worst_performer":\s*\{(.*?)\}\s*if worst',
        src,
        re.DOTALL,
    )
    assert bp_block is not None, "Could not locate best_performer dict construction"
    assert wp_block is not None, "Could not locate worst_performer dict construction"
    assert "all_time_return_pct" in bp_block.group(1), (
        "best_performer dict must expose all_time_return_pct"
    )
    assert "all_time_return_pct" in wp_block.group(1), (
        "worst_performer dict must expose all_time_return_pct"
    )
