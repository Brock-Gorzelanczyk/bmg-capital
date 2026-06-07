"""Tests for position_monitor time-based guards — FIX 1 + FIX F verification.

These ensure hold_max_hours, hold_max_days, and hold_min_days are all enforced
and that the priority order is: min-hold skip → time-exit → stop → target.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch


def _make_pos(symbol, avg_cost_usd, qty, opened_hours_ago, stop_usd=None, target_usd=None):
    pos = MagicMock()
    pos.symbol = symbol
    pos.avg_cost_cents = int(avg_cost_usd * 100)
    pos.qty = qty
    pos.opened_at = datetime.now(timezone.utc) - timedelta(hours=opened_hours_ago)
    pos.closed_at = None
    pos.stop_price_usd = stop_usd
    pos.target_price_usd = target_usd
    pos.trailing_stop_activated = False
    pos.allocation_id = 1
    pos.id = 1
    return pos


def _make_profile_cfg(**kwargs):
    return kwargs


def test_hold_max_hours_force_exits_stale_position():
    """Position held > hold_max_hours must be closed with hold_max_hours_force_exit."""
    from strategy_lab.core.position_monitor import run_position_monitor

    pos = _make_pos("ETH/USD", avg_cost_usd=3195.0, qty=0.8, opened_hours_ago=25)
    profile_cfg = _make_profile_cfg(hold_max_hours=8)

    closed_positions = []

    def fake_close(db, p, alloc, price, reason, now):
        closed_positions.append((p.symbol, reason))

    with (
        patch("strategy_lab.core.position_monitor.SessionLocal") as mock_session,
        patch("strategy_lab.core.position_monitor._get_current_prices", return_value={"ETH/USD": 2500.0}),
        patch("strategy_lab.core.position_monitor._close_position", side_effect=fake_close),
    ):
        db = MagicMock()
        mock_session.return_value = db

        alloc = MagicMock()
        alloc.profile_id = 1
        profile = MagicMock()
        profile.config_json = profile_cfg
        db.query.return_value.filter.return_value.all.return_value = [pos]
        db.get.side_effect = lambda model, pk: alloc if "Allocation" in str(model) else profile

        run_position_monitor()

    assert any(r == "hold_max_hours_force_exit" for _, r in closed_positions), \
        "Position should have been closed with hold_max_hours_force_exit"


def test_hold_min_days_prevents_early_exit():
    """Position held < hold_min_days must NOT be stopped out even if stop is hit."""
    from strategy_lab.core.position_monitor import run_position_monitor

    # Stop price is hit (current price < stop), but held only 2h vs min 1 day
    pos = _make_pos("AAPL", avg_cost_usd=180.0, qty=10, opened_hours_ago=2,
                    stop_usd=175.0)  # stop would trigger at 174
    profile_cfg = _make_profile_cfg(hold_min_days=1)

    closed_positions = []

    def fake_close(db, p, alloc, price, reason, now):
        closed_positions.append((p.symbol, reason))

    with (
        patch("strategy_lab.core.position_monitor.SessionLocal") as mock_session,
        patch("strategy_lab.core.position_monitor._get_current_prices", return_value={"AAPL": 174.0}),
        patch("strategy_lab.core.position_monitor._close_position", side_effect=fake_close),
    ):
        db = MagicMock()
        mock_session.return_value = db

        alloc = MagicMock()
        profile = MagicMock()
        profile.config_json = profile_cfg
        db.query.return_value.filter.return_value.all.return_value = [pos]
        db.get.side_effect = lambda model, pk: alloc if "Allocation" in str(model) else profile

        run_position_monitor()

    assert len(closed_positions) == 0, \
        "Position should NOT be closed when hold_min_days not yet elapsed"


def test_hold_max_days_converted_to_hours():
    """hold_max_days: 2 must close a position held 49 hours."""
    from strategy_lab.core.position_monitor import run_position_monitor

    pos = _make_pos("SOL/USD", avg_cost_usd=150.0, qty=5.0, opened_hours_ago=49)
    profile_cfg = _make_profile_cfg(hold_max_days=2)

    closed_positions = []

    def fake_close(db, p, alloc, price, reason, now):
        closed_positions.append((p.symbol, reason))

    with (
        patch("strategy_lab.core.position_monitor.SessionLocal") as mock_session,
        patch("strategy_lab.core.position_monitor._get_current_prices", return_value={"SOL/USD": 155.0}),
        patch("strategy_lab.core.position_monitor._close_position", side_effect=fake_close),
    ):
        db = MagicMock()
        mock_session.return_value = db

        alloc = MagicMock()
        profile = MagicMock()
        profile.config_json = profile_cfg
        db.query.return_value.filter.return_value.all.return_value = [pos]
        db.get.side_effect = lambda model, pk: alloc if "Allocation" in str(model) else profile

        run_position_monitor()

    assert any(r == "hold_max_hours_force_exit" for _, r in closed_positions), \
        "Position held 49h vs 48h limit should be force-closed"
