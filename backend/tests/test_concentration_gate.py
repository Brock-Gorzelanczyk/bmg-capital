"""Tests for strategy_lab.core.concentration_gate.check_concentration.

Coverage:
  - under-cap allows
  - at-cap allows (boundary)
  - over-cap blocks (single-name 8%)
  - ETF skips sector check (mock get_sector → None)
  - missing user → safe default allow + warning log
  - sector cap blocks at > 25%
  - cluster gate blocks at >= 3 positions in sector AND post > 15%
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch


def _mk_db(total_capital_cents: int, alloc_ids: list, open_positions_by_sym: dict,
           all_open_positions: list = None):
    """Build a MagicMock SQLAlchemy session whose .execute(text, params)
    returns a row depending on which SELECT is being run.

    open_positions_by_sym: {symbol: notional_dollars} for single-name lookups
    all_open_positions: optional list of (symbol, qty, avg_cost_cents) rows
      used for sector_open_positions; if None, derived from open_positions_by_sym
      treating each position as qty=1, avg_cost_cents=notional*100.
    """
    if all_open_positions is None:
        all_open_positions = [
            (sym, 1.0, float(notional) * 100.0)
            for sym, notional in open_positions_by_sym.items()
        ]

    def _execute(stmt, params=None):
        # SQLAlchemy TextClause stringifies to its SQL body. Pattern-match by
        # the leading SELECT shape — keeps the mock decoupled from formatting.
        sql = str(stmt).strip().lower()
        result = MagicMock()
        if "sum(starting_capital_cents)" in sql:
            result.fetchone.return_value = (total_capital_cents,)
        elif "select id from bot_allocations" in sql:
            result.fetchall.return_value = [(a,) for a in alloc_ids]
        elif "sum(qty * avg_cost_cents)" in sql:
            sym = (params or {}).get("sym")
            n = float(open_positions_by_sym.get(sym, 0.0))
            result.fetchone.return_value = (n * 100.0,)  # back to cents
        elif "select symbol, qty, avg_cost_cents" in sql:
            result.fetchall.return_value = all_open_positions
        else:
            result.fetchone.return_value = (0,)
            result.fetchall.return_value = []
        return result

    db = MagicMock()
    db.execute.side_effect = _execute
    return db


def test_under_cap_allows():
    from strategy_lab.core.concentration_gate import check_concentration

    # $1M total, AAPL adds $50K (5%), no existing → under 8% cap
    db = _mk_db(
        total_capital_cents=100_000_000,
        alloc_ids=[1, 2],
        open_positions_by_sym={},
        all_open_positions=[],
    )
    allowed, reason = check_concentration(
        db, user_id=1, allocation_id=1, symbol="AAPL",
        proposed_notional=50_000.0, profile={},
    )
    assert allowed is True
    assert reason == ""


def test_at_cap_allows():
    """At exactly 8% the gate should allow (strict > comparison)."""
    from strategy_lab.core.concentration_gate import check_concentration

    # $1M total, AAPL existing $30K + proposed $50K = $80K = 8.0% exactly
    db = _mk_db(
        total_capital_cents=100_000_000,
        alloc_ids=[1],
        open_positions_by_sym={"AAPL": 30_000.0},
        all_open_positions=[("AAPL", 1.0, 30_000.0 * 100.0)],
    )
    allowed, reason = check_concentration(
        db, user_id=1, allocation_id=1, symbol="AAPL",
        proposed_notional=50_000.0, profile={},
    )
    assert allowed is True, f"at-cap should allow, got reason={reason}"


def test_over_cap_blocks():
    """> 8% single-name → block."""
    from strategy_lab.core.concentration_gate import check_concentration

    # $1M total, AAPL existing $50K + proposed $40K = $90K = 9.0% > 8%
    db = _mk_db(
        total_capital_cents=100_000_000,
        alloc_ids=[1],
        open_positions_by_sym={"AAPL": 50_000.0},
        all_open_positions=[("AAPL", 1.0, 50_000.0 * 100.0)],
    )
    allowed, reason = check_concentration(
        db, user_id=1, allocation_id=1, symbol="AAPL",
        proposed_notional=40_000.0, profile={},
    )
    assert allowed is False
    assert "single-name" in reason.lower()


def test_etf_skips_sector_check():
    """ETF symbols (get_sector → None) bypass sector + cluster gates."""
    from strategy_lab.core.concentration_gate import check_concentration

    # $1M total, SPY proposed $400K — would violate 25% sector cap if sectorized.
    # But ETF skip means we only hit single-name (40% > 8% → block on single-name).
    # So test with $50K proposal: under single-name cap, would otherwise be over
    # sector cap if SPY were sectorized.
    db = _mk_db(
        total_capital_cents=100_000_000,
        alloc_ids=[1],
        open_positions_by_sym={},
        all_open_positions=[],
    )
    with patch("strategy_lab.core.concentration_gate.get_sector", return_value=None):
        allowed, reason = check_concentration(
            db, user_id=1, allocation_id=1, symbol="SPY",
            proposed_notional=50_000.0, profile={},
        )
    assert allowed is True, f"ETF should bypass sector check; got reason={reason}"
    assert reason == ""


def test_missing_user_safe_default_allow(caplog):
    """No starting capital → allow with warning, do not crash."""
    from strategy_lab.core.concentration_gate import check_concentration

    db = _mk_db(
        total_capital_cents=0,
        alloc_ids=[],
        open_positions_by_sym={},
        all_open_positions=[],
    )
    with caplog.at_level(logging.WARNING, logger="strategy_lab.core.concentration_gate"):
        allowed, reason = check_concentration(
            db, user_id=999, allocation_id=1, symbol="AAPL",
            proposed_notional=10_000.0, profile={},
        )
    assert allowed is True
    assert reason == ""
    # The warning is the "safe default" channel — make sure something fired.
    assert any("zero starting capital" in r.message.lower()
               or "user_total_capital" in r.message.lower()
               for r in caplog.records), (
        f"expected warn log for missing user, got: {[r.message for r in caplog.records]}"
    )


def test_sector_cap_blocks():
    """Over 25% sector exposure → block."""
    from strategy_lab.core.concentration_gate import check_concentration

    # $1M total. Two AAPL-tech positions worth $150K, proposed MSFT $120K.
    # Sector total = $150K + $120K = $270K = 27.0% > 25% → block.
    # Single name MSFT = $120K = 12% — would block on single-name first
    # unless we keep it under 8%. Use MSFT proposed $79K to stay under 8%.
    # Cluster total = $150K + $79K = $229K = 22.9% — under sector cap → pass.
    # Need a different setup: split AAPL into smaller positions.
    db = _mk_db(
        total_capital_cents=100_000_000,
        alloc_ids=[1],
        open_positions_by_sym={"AAPL": 70_000.0, "NVDA": 70_000.0, "GOOGL": 70_000.0},
        all_open_positions=[
            ("AAPL", 1.0, 70_000.0 * 100.0),
            ("NVDA", 1.0, 70_000.0 * 100.0),
            ("GOOGL", 1.0, 70_000.0 * 100.0),
        ],
    )
    # Propose MSFT $70K — single-name OK (7%), sector total = 210K + 70K = 280K (28%) > 25%
    allowed, reason = check_concentration(
        db, user_id=1, allocation_id=1, symbol="MSFT",
        proposed_notional=70_000.0, profile={},
    )
    assert allowed is False
    assert "sector" in reason.lower()


def test_cluster_gate_blocks():
    """3+ positions in sector AND post > 15% → block as cluster."""
    from strategy_lab.core.concentration_gate import check_concentration

    # $1M total, 3 existing tech positions @ $40K each = $120K.
    # Propose MSFT $40K — single name 4% OK, sector total $160K = 16% (OK <25%),
    # but cluster has 3 existing positions and post = 16% > 15% → block.
    db = _mk_db(
        total_capital_cents=100_000_000,
        alloc_ids=[1],
        open_positions_by_sym={"AAPL": 40_000.0, "NVDA": 40_000.0, "GOOGL": 40_000.0},
        all_open_positions=[
            ("AAPL", 1.0, 40_000.0 * 100.0),
            ("NVDA", 1.0, 40_000.0 * 100.0),
            ("GOOGL", 1.0, 40_000.0 * 100.0),
        ],
    )
    allowed, reason = check_concentration(
        db, user_id=1, allocation_id=1, symbol="MSFT",
        proposed_notional=40_000.0, profile={},
    )
    assert allowed is False
    assert "cluster" in reason.lower()


def test_env_override_single_name(monkeypatch):
    """SINGLE_NAME_CAP_PCT env var raises the cap."""
    from strategy_lab.core.concentration_gate import check_concentration

    # Same setup as test_over_cap_blocks (9% exposure), but override cap to 10%.
    db = _mk_db(
        total_capital_cents=100_000_000,
        alloc_ids=[1],
        open_positions_by_sym={"AAPL": 50_000.0},
        all_open_positions=[("AAPL", 1.0, 50_000.0 * 100.0)],
    )
    monkeypatch.setenv("SINGLE_NAME_CAP_PCT", "10.0")
    allowed, reason = check_concentration(
        db, user_id=1, allocation_id=1, symbol="AAPL",
        proposed_notional=40_000.0, profile={},
    )
    assert allowed is True, f"override should allow 9% under 10% cap, got {reason}"
