"""Tests for strategy_lab.core.fund_halt.

Spec (vault context/06-decision-history.md):
  - Drawdown <= -1.5% from rolling 90d peak  -> pause new allocations
  - Drawdown >  -1.5%                        -> allow
  - Missing peak data                        -> safe-default allow

The fund-halt module reads canonical PV and bot_daily_pnl via mocked
shims so this test never touches a real database.
"""
from __future__ import annotations

import logging
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

# ─── conftest does not pre-mock app.core — wire a stub here so
# strategy_lab.core.fund_halt can `from app.core.canonical import ...`.
if "app.core" not in sys.modules:
    _app_core = types.ModuleType("app.core")
    _app_core.__spec__ = None
    _app_core_canonical = types.ModuleType("app.core.canonical")
    _app_core_canonical.__spec__ = None
    _app_core_canonical.get_canonical_portfolio_state = MagicMock(
        name="get_canonical_portfolio_state",
        return_value={"portfolio_value_cents": 0},
    )
    _app_core.canonical = _app_core_canonical
    sys.modules["app.core"] = _app_core
    sys.modules["app.core.canonical"] = _app_core_canonical
    # Attach to parent so getattr traversal works
    import app  # noqa: F401  (mocked in conftest)
    sys.modules["app"].core = _app_core


# ─── helpers ───────────────────────────────────────────────────────────────

def _patch_canonical(pv_cents):
    """Patch get_canonical_portfolio_state to return a fixed PV.
    The stub is wired at module load (top of this file). fund_halt does a
    local `from app.core.canonical import ...` inside its function, so we
    patch the attribute on the stub module.
    """
    return patch.object(
        sys.modules["app.core.canonical"],
        "get_canonical_portfolio_state",
        return_value={"portfolio_value_cents": pv_cents},
    )


def _patch_peak(peak_cents):
    """Patch _rolling_peak_cents to return a fixed peak. Avoids fighting
    with SQLAlchemy filter-expression comparisons against MagicMock'd
    model columns (the model classes are stubbed in conftest).
    """
    import strategy_lab.core.fund_halt as _fh
    return patch.object(_fh, "_rolling_peak_cents", return_value=peak_cents)


def _patch_peak_empty_with_fallback_log():
    """Simulate the empty-table fallback path. Calls the real function
    against a mock db that returns an empty row list, so the INFO log
    that says 'no bot_daily_pnl rows' actually fires.
    """
    db = MagicMock(name="db")
    chain = db.query.return_value
    chain.join.return_value = chain
    chain.filter.return_value = chain
    chain.group_by.return_value = chain
    chain.all.return_value = []
    return db


# ─── importable + signature ────────────────────────────────────────────────

def test_check_fund_halt_is_importable():
    from strategy_lab.core.fund_halt import check_fund_halt
    assert callable(check_fund_halt)


def test_compute_drawdown_is_importable():
    from strategy_lab.core.fund_halt import compute_drawdown
    assert callable(compute_drawdown)


# ─── blocked: drawdown breaches threshold ──────────────────────────────────

def test_blocked_when_drawdown_below_minus_one_point_five():
    """Peak = $1,000,000. Current = $980,000. dd = -2.0% -> blocked."""
    from strategy_lab.core.fund_halt import check_fund_halt

    db = MagicMock(name="db")
    with _patch_peak(100_000_000_00), _patch_canonical(98_000_000_00):
        allowed, reason = check_fund_halt(db, user_id=1)

    assert allowed is False
    assert "dd=" in reason
    assert "pause" in reason


def test_blocked_at_exactly_minus_one_point_five():
    """dd == -1.5% is at the threshold and must block (<=)."""
    from strategy_lab.core.fund_halt import check_fund_halt

    db = MagicMock(name="db")
    with _patch_peak(100_000_000_00), _patch_canonical(98_500_000_00):
        allowed, reason = check_fund_halt(db, user_id=1)

    assert allowed is False
    assert reason  # non-empty


# ─── allowed: drawdown above threshold ─────────────────────────────────────

def test_allowed_when_drawdown_above_threshold():
    """Peak = $1,000,000. Current = $995,000. dd = -0.5% -> allowed."""
    from strategy_lab.core.fund_halt import check_fund_halt

    db = MagicMock(name="db")
    with _patch_peak(100_000_000_00), _patch_canonical(99_500_000_00):
        allowed, reason = check_fund_halt(db, user_id=1)

    assert allowed is True
    assert reason == ""


def test_allowed_when_at_or_above_peak():
    """Current >= peak -> dd >= 0 -> allowed."""
    from strategy_lab.core.fund_halt import check_fund_halt

    db = MagicMock(name="db")
    with _patch_peak(100_000_000_00), _patch_canonical(105_000_000_00):
        allowed, reason = check_fund_halt(db, user_id=1)

    assert allowed is True
    assert reason == ""


# ─── safe defaults ─────────────────────────────────────────────────────────

def test_missing_daily_data_safe_default_allowed(caplog):
    """Empty bot_daily_pnl -> peak falls back to current -> dd=0 -> allowed.
    Must also emit an INFO log so ops can see the fallback path.
    """
    from strategy_lab.core.fund_halt import check_fund_halt

    db = _patch_peak_empty_with_fallback_log()
    with _patch_canonical(100_000_000_00), caplog.at_level(logging.INFO, logger="strategy_lab.core.fund_halt"):
        allowed, reason = check_fund_halt(db, user_id=1)

    assert allowed is True
    assert reason == ""
    # Confirm the warning/info fallback path actually fired (empty rows
    # or query failure both end up safe-defaulted to "allowed").
    msgs = " ".join(rec.getMessage() for rec in caplog.records)
    assert ("no bot_daily_pnl" in msgs) or ("peak query failed" in msgs) or ("using current PV" in msgs)


def test_no_canonical_pv_safe_default_allowed():
    """canonical returns 0 PV -> allowed (cannot compute dd)."""
    from strategy_lab.core.fund_halt import check_fund_halt

    db = MagicMock(name="db")
    with patch.object(
        sys.modules["app.core.canonical"],
        "get_canonical_portfolio_state",
        return_value={"portfolio_value_cents": 0},
    ):
        allowed, reason = check_fund_halt(db, user_id=1)

    assert allowed is True
    assert reason == ""


def test_query_exception_safe_default_allowed():
    """Underlying query raises -> safe-default allow, never propagate."""
    from strategy_lab.core.fund_halt import check_fund_halt

    db = MagicMock(name="db")
    db.query.side_effect = RuntimeError("DB exploded")

    with _patch_canonical(100_000_000_00):
        allowed, reason = check_fund_halt(db, user_id=1)

    # Peak query failed -> peak == current -> dd == 0 -> allowed
    assert allowed is True
    assert reason == ""


# ─── env overrides ─────────────────────────────────────────────────────────

def test_env_override_loosens_pause_threshold(monkeypatch):
    """Setting FUND_HALT_PAUSE_PCT=-5.0 means a -2% drawdown should be allowed."""
    from strategy_lab.core.fund_halt import check_fund_halt

    monkeypatch.setenv("FUND_HALT_PAUSE_PCT", "-5.0")

    db = MagicMock(name="db")
    with _patch_peak(100_000_000_00), _patch_canonical(98_000_000_00):
        allowed, reason = check_fund_halt(db, user_id=1)

    assert allowed is True
    assert reason == ""


def test_env_override_tightens_pause_threshold(monkeypatch):
    """Setting FUND_HALT_PAUSE_PCT=-0.5 blocks at -1%."""
    from strategy_lab.core.fund_halt import check_fund_halt

    monkeypatch.setenv("FUND_HALT_PAUSE_PCT", "-0.5")

    db = MagicMock(name="db")
    with _patch_peak(100_000_000_00), _patch_canonical(99_000_000_00):
        allowed, reason = check_fund_halt(db, user_id=1)

    assert allowed is False
    assert "dd=" in reason
