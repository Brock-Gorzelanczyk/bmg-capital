"""Tests for risk_overlay.apply_overlay — FIX A verification.

These tests fail loud if apply_overlay is ever removed or renamed,
which would silently re-disable the consecutive-loss halt and regime gates.
"""
from unittest.mock import MagicMock

import pytest


def _make_signal(symbol="AAPL", side="buy", confidence=0.70, size_hint=0.10):
    from strategy_lab.core.signals import Signal
    return Signal(symbol=symbol, side=side, confidence=confidence,
                  size_hint=size_hint, reason="test", strategy="test")


def test_apply_overlay_is_importable():
    """apply_overlay must be importable — the naming-mismatch bug must not regress."""
    from strategy_lab.core.risk_overlay import apply_overlay
    assert callable(apply_overlay)


def test_apply_overlay_passes_normal_signals():
    """In a normal regime, all buy signals should pass through."""
    from strategy_lab.core.risk_overlay import apply_overlay

    signals = [_make_signal("AAPL", "buy"), _make_signal("MSFT", "buy")]
    regime = {"vix_regime": "mid", "trend_regime": "bull"}
    profile = {"risk_overlay": {}}
    db = MagicMock()
    # BotDailyPnL query returns None (no loss data)
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    result = apply_overlay(signals, profile, regime, db)
    assert len(result) == 2
    assert all(s.side == "buy" for s in result)


def test_apply_overlay_blocks_all_on_vix_panic():
    """VIX panic regime must block ALL new buy/sell entries."""
    from strategy_lab.core.risk_overlay import apply_overlay
    from strategy_lab.core.signals import Signal

    signals = [
        _make_signal("AAPL", "buy"),
        _make_signal("MSFT", "sell"),
        Signal(symbol="SPY", side="hold", confidence=0.5, size_hint=0.0,
               reason="hold", strategy="test"),
    ]
    regime = {"vix_regime": "panic"}
    profile = {"risk_overlay": {}}
    db = MagicMock()

    result = apply_overlay(signals, profile, regime, db)
    # Only the hold signal should survive
    assert len(result) == 1
    assert result[0].side == "hold"


def test_apply_overlay_halves_size_on_vix_high():
    """VIX high regime should halve size_hint on passing signals."""
    from strategy_lab.core.risk_overlay import apply_overlay

    sig = _make_signal("AAPL", "buy", size_hint=0.10)
    regime = {"vix_regime": "high"}
    profile = {"risk_overlay": {}}
    db = MagicMock()
    db.query.return_value.filter.return_value.first.return_value = None
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []

    result = apply_overlay([sig], profile, regime, db)
    assert len(result) == 1
    assert result[0].size_hint == pytest.approx(0.05, abs=0.001)


def test_apply_overlay_hold_signals_always_pass():
    """hold signals must always pass regardless of regime."""
    from strategy_lab.core.risk_overlay import apply_overlay
    from strategy_lab.core.signals import Signal

    hold_sig = Signal(symbol="BTC/USD", side="hold", confidence=0.5, size_hint=0.0,
                      reason="hold", strategy="test")
    regime = {"vix_regime": "panic"}
    profile = {"risk_overlay": {}}
    db = MagicMock()

    result = apply_overlay([hold_sig], profile, regime, db)
    assert len(result) == 1
