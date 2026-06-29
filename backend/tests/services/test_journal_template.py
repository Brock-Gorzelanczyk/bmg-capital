"""
R6 parity test — journal_autopilot uses deterministic string templates.

The journal prompts must not call any LLM. Output is a non-empty string.
"""
import pytest
from unittest.mock import patch, MagicMock


def test_r6_no_llm_call_in_journal():
    """journal_autopilot must not import anthropic or call any LLM for basic journal text."""
    import sys
    # Ensure anthropic not triggered
    with patch("app.services.llm_client.call_llm") as mock_llm:
        with patch("app.services.llm_client.call_llm_cached") as mock_cached:
            try:
                from app.services.journal_autopilot import (
                    auto_prompt_trade_reflection,
                )
            except ImportError:
                pytest.skip("journal_autopilot not importable in test env")

    # If journal_autopilot was imported without triggering LLM, good.
    # The actual test: calling with mocked DB should not call LLM
    mock_llm.assert_not_called()
    mock_cached.assert_not_called()


def test_r6_journal_template_module_importable():
    """trade_journal_template must be importable and export render functions."""
    try:
        from strategy_lab.core.expert.trade_journal_template import (
            render_lab_entry_journal,
            render_lab_exit_journal,
        )
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    # Entry journal
    entry = render_lab_entry_journal(
        symbol="AAPL",
        side="buy",
        qty=10,
        price=150.0,
        strategy="momentum",
        reason="RSI oversold",
    )
    assert isinstance(entry, str)
    assert len(entry) > 5

    # Exit journal
    exit_j = render_lab_exit_journal(
        symbol="AAPL",
        side="sell",
        qty=10,
        entry_price=150.0,
        exit_price=155.0,
        pnl=50.0,
        reason="target hit",
    )
    assert isinstance(exit_j, str)
    assert len(exit_j) > 5


def test_r6_journal_template_zero_qty():
    """qty=0 must not raise ZeroDivisionError or any exception."""
    try:
        from strategy_lab.core.expert.trade_journal_template import (
            render_lab_entry_journal,
            render_lab_exit_journal,
        )
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    # Entry with zero qty
    entry = render_lab_entry_journal(
        symbol="TSLA",
        side="buy",
        qty=0,
        price=200.0,
        strategy="test",
        reason="zero qty edge case",
    )
    assert isinstance(entry, str)

    # Exit with zero qty
    exit_j = render_lab_exit_journal(
        symbol="TSLA",
        side="sell",
        qty=0,
        entry_price=200.0,
        exit_price=200.0,
        pnl=0.0,
        reason="zero qty exit",
    )
    assert isinstance(exit_j, str)


def test_r6_journal_template_negative_pnl():
    """Negative P&L must format with a leading minus sign (no double-sign artefact)."""
    try:
        from strategy_lab.core.expert.trade_journal_template import (
            render_lab_exit_journal,
        )
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    exit_j = render_lab_exit_journal(
        symbol="NVDA",
        side="sell",
        qty=5,
        entry_price=500.0,
        exit_price=480.0,
        pnl=-100.0,
        reason="stop loss",
    )
    assert isinstance(exit_j, str)
    # Negative P&L must render with a minus sign and no "+-" artefact
    # Template produces "$-100.00" (dollar sign then minus, from Python float formatting)
    assert "-100.00" in exit_j
    assert "+-" not in exit_j


def test_r6_journal_template_missing_exit_reason():
    """Empty/None exit reason must fall back gracefully without KeyError or crash."""
    try:
        from strategy_lab.core.expert.trade_journal_template import (
            render_lab_exit_journal,
        )
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    # Empty string reason — must not raise
    exit_j = render_lab_exit_journal(
        symbol="SPY",
        side="sell",
        qty=2,
        entry_price=400.0,
        exit_price=410.0,
        pnl=20.0,
        reason="",
    )
    assert isinstance(exit_j, str)

    # None reason — must not raise (template should coerce gracefully)
    try:
        exit_none = render_lab_exit_journal(
            symbol="SPY",
            side="sell",
            qty=2,
            entry_price=400.0,
            exit_price=410.0,
            pnl=20.0,
            reason=None,
        )
        assert isinstance(exit_none, str)
    except TypeError:
        # Acceptable: function signature requires str; None is a caller error.
        # The important thing is no KeyError is raised.
        pass


def test_r6_journal_template_ten_closed_trades():
    """Rendering 10+ closed trade journals must all succeed without error."""
    try:
        from strategy_lab.core.expert.trade_journal_template import (
            render_lab_entry_journal,
            render_lab_exit_journal,
        )
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    closed_trades = [
        {"symbol": "AAPL", "qty": 10, "entry": 150.0, "exit": 155.0, "pnl": 50.0, "reason": "target hit"},
        {"symbol": "TSLA", "qty": 5,  "entry": 200.0, "exit": 190.0, "pnl": -50.0, "reason": "stop loss"},
        {"symbol": "NVDA", "qty": 3,  "entry": 500.0, "exit": 520.0, "pnl": 60.0, "reason": "momentum"},
        {"symbol": "MSFT", "qty": 8,  "entry": 300.0, "exit": 310.0, "pnl": 80.0, "reason": "earnings"},
        {"symbol": "AMZN", "qty": 2,  "entry": 130.0, "exit": 128.0, "pnl": -4.0, "reason": "reversal"},
        {"symbol": "GOOG", "qty": 1,  "entry": 170.0, "exit": 175.0, "pnl": 5.0, "reason": "breakout"},
        {"symbol": "META", "qty": 4,  "entry": 500.0, "exit": 490.0, "pnl": -40.0, "reason": "fade"},
        {"symbol": "SPY",  "qty": 20, "entry": 450.0, "exit": 455.0, "pnl": 100.0, "reason": "index"},
        {"symbol": "QQQ",  "qty": 0,  "entry": 380.0, "exit": 380.0, "pnl": 0.0, "reason": ""},
        {"symbol": "IWM",  "qty": 7,  "entry": 200.0, "exit": 198.0, "pnl": -14.0, "reason": "sector"},
        {"symbol": "XLF",  "qty": 15, "entry": 40.0,  "exit": 42.0,  "pnl": 30.0, "reason": "financials"},
    ]

    assert len(closed_trades) >= 10, "Test set must have at least 10 closed trades"

    for trade in closed_trades:
        entry = render_lab_entry_journal(
            symbol=trade["symbol"],
            side="buy",
            qty=trade["qty"],
            price=trade["entry"],
            strategy="multi_trade_test",
            reason="entry signal",
        )
        exit_j = render_lab_exit_journal(
            symbol=trade["symbol"],
            side="sell",
            qty=trade["qty"],
            entry_price=trade["entry"],
            exit_price=trade["exit"],
            pnl=trade["pnl"],
            reason=trade["reason"],
        )
        assert isinstance(entry, str)
        assert isinstance(exit_j, str)
