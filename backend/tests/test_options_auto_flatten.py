"""STOP-THE-LINE #2 (2026-07-15) — transactional order+position insert.

Order placement and DB position row succeed or fail together. On DB
insert failure, the runner auto-flattens each already-filled leg at
Alpaca so we never carry a position we can't track.

Acceptance from spec: closes the leak that created 45 untracked legs.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_auto_flatten_closes_each_leg():
    """A 2-leg mleg spread with DB insert failure must trigger sell/buy
    close orders for BOTH legs — the long-leg buy gets a sell close, the
    short-leg sell gets a buy close."""
    from strategy_lab.runner import _auto_flatten_option_legs

    leg_rows = [
        {"symbol": "BABA260828C00111000", "side_trade": "buy",  "qty": 5},  # long → close via sell
        {"symbol": "BABA260828C00112000", "side_trade": "sell", "qty": 5},  # short → close via buy
    ]

    fake_broker = MagicMock()
    fake_broker.submit_options_order.return_value = {"status_code": 200, "order_id": "flatten-test"}

    with patch("strategy_lab.core.execution.get_broker", return_value=fake_broker):
        result = _auto_flatten_option_legs(leg_rows, position_side="long")

    # Both legs closed
    assert fake_broker.submit_options_order.call_count == 2
    calls = fake_broker.submit_options_order.call_args_list
    # First leg: long → close side "sell"
    assert calls[0].kwargs["contract_symbol"] == "BABA260828C00111000"
    assert calls[0].kwargs["side"] == "sell"
    assert calls[0].kwargs["contracts"] == 5
    # Second leg: short → close side "buy"
    assert calls[1].kwargs["contract_symbol"] == "BABA260828C00112000"
    assert calls[1].kwargs["side"] == "buy"
    assert calls[1].kwargs["contracts"] == 5
    # Result summary mentions both legs
    assert "BABA260828C00111000=closed" in result
    assert "BABA260828C00112000=closed" in result


def test_auto_flatten_reports_reject_when_alpaca_declines():
    """If Alpaca refuses the close order (status != 200/201), the summary
    must NAME the leg + status so a human sees a loud "ORPHAN AT BROKER"."""
    from strategy_lab.runner import _auto_flatten_option_legs

    leg_rows = [
        {"symbol": "META260828C00655000", "side_trade": "buy", "qty": 5},
    ]

    fake_broker = MagicMock()
    fake_broker.submit_options_order.return_value = {"status_code": 403, "body": "insufficient options bp"}

    with patch("strategy_lab.core.execution.get_broker", return_value=fake_broker):
        result = _auto_flatten_option_legs(leg_rows, position_side="long")

    assert "META260828C00655000=REJECT" in result
    assert "403" in result


def test_auto_flatten_survives_broker_unavailable():
    """If get_broker itself raises, the flatten helper returns a summary
    string (never raises) so the caller can persist it in a hold-signal.
    That's the promise: 'never raises — if the flatten itself fails, we
    log LOUD so a human can reconcile manually.'"""
    from strategy_lab.runner import _auto_flatten_option_legs

    with patch("strategy_lab.core.execution.get_broker", side_effect=RuntimeError("no creds")):
        result = _auto_flatten_option_legs(
            [{"symbol": "SPY260828C00500000", "side_trade": "buy", "qty": 1}],
            position_side="long",
        )
    assert "broker_unavailable" in result
    assert "RuntimeError" in result


def test_auto_flatten_no_legs_is_noop():
    """Empty leg_rows returns a benign message — nothing to close, no crash."""
    from strategy_lab.runner import _auto_flatten_option_legs
    assert _auto_flatten_option_legs([], "long") == "no legs to flatten"
