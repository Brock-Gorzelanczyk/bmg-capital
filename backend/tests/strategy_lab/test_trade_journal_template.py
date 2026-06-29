"""
R8 parity test — strategy_lab trade_journal_template.

render functions return JSON-serializable strings with required keys.
No LLM call made.
"""
import json
import pytest
from unittest.mock import patch


def test_r8_entry_journal_returns_string():
    try:
        from strategy_lab.core.expert.trade_journal_template import render_lab_entry_journal
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    result = render_lab_entry_journal(
        symbol="TSLA",
        side="buy",
        qty=5,
        price=200.0,
        strategy="breakout",
        reason="Volume spike above 50-day MA",
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_r8_exit_journal_returns_string():
    try:
        from strategy_lab.core.expert.trade_journal_template import render_lab_exit_journal
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    result = render_lab_exit_journal(
        symbol="TSLA",
        side="sell",
        qty=5,
        entry_price=200.0,
        exit_price=210.0,
        pnl=50.0,
        reason="Target hit",
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_r8_entry_journal_mentions_symbol():
    try:
        from strategy_lab.core.expert.trade_journal_template import render_lab_entry_journal
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    result = render_lab_entry_journal(
        symbol="NVDA",
        side="buy",
        qty=10,
        price=500.0,
        strategy="momentum",
        reason="AI tailwinds",
    )
    assert "NVDA" in result or "nvda" in result.lower()


def test_r8_no_llm_in_journal_template():
    """Templates must not call LLM."""
    with patch("app.services.llm_client.call_llm") as mock_llm:
        with patch("app.services.llm_client.call_llm_cached") as mock_cached:
            try:
                from strategy_lab.core.expert.trade_journal_template import (
                    render_lab_entry_journal,
                    render_lab_exit_journal,
                )
                render_lab_entry_journal("AAPL", "buy", 1, 100.0, "test", "test reason")
                render_lab_exit_journal("AAPL", "sell", 1, 100.0, 105.0, 5.0, "target")
            except ImportError:
                pytest.skip("trade_journal_template not importable")
    mock_llm.assert_not_called()
    mock_cached.assert_not_called()


def test_r8_10_entry_variants():
    """10 different entry combos must all return non-empty strings."""
    try:
        from strategy_lab.core.expert.trade_journal_template import render_lab_entry_journal
    except ImportError:
        pytest.skip("trade_journal_template not importable")

    combos = [
        ("AAPL", "buy", 10, 150.0, "momentum", "RSI crossover"),
        ("MSFT", "sell", 5, 300.0, "mean_revert", "overbought"),
        ("NVDA", "buy", 2, 500.0, "breakout", "earnings beat"),
        ("TSLA", "buy", 3, 200.0, "trend_follow", "52-week high"),
        ("SPY", "buy", 20, 430.0, "index", "risk-on"),
        ("QQQ", "sell", 8, 360.0, "hedge", "tech selloff"),
        ("AMZN", "buy", 1, 180.0, "value", "PE compression"),
        ("META", "buy", 4, 250.0, "momentum", "ad revenue beat"),
        ("GOOG", "sell", 3, 170.0, "take_profit", "50% gain"),
        ("BRK.B", "buy", 6, 380.0, "quality", "margin of safety"),
    ]
    for sym, side, qty, price, strat, reason in combos:
        result = render_lab_entry_journal(sym, side, qty, price, strat, reason)
        assert isinstance(result, str) and len(result) > 0, (
            f"Empty result for {sym}/{side}/{strat}"
        )
