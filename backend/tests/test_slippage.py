"""Tests for strategy_lab.core.slippage — paper-fill haircut.

Spec (Phase 4):
- Default 8 bps per side (entry + exit = 16 bps round-trip).
- buy worsens UP, sell worsens DOWN.
- Configurable via env SLIPPAGE_HAIRCUT_BPS.
- Round-trip on flat trade nets to -2 * bps * notional, not zero.
"""
import os
import importlib
import pytest


@pytest.fixture(autouse=True)
def _reset_env_and_module(monkeypatch):
    """Ensure SLIPPAGE_HAIRCUT_BPS isn't leaked between tests."""
    monkeypatch.delenv("SLIPPAGE_HAIRCUT_BPS", raising=False)
    # Re-import to make sure module-level state isn't cached across tests.
    import strategy_lab.core.slippage as slip
    importlib.reload(slip)
    yield slip


def test_default_haircut_is_eight_bps(_reset_env_and_module):
    slip = _reset_env_and_module
    assert slip.haircut_bps() == 8.0


def test_env_override(monkeypatch):
    monkeypatch.setenv("SLIPPAGE_HAIRCUT_BPS", "12")
    import strategy_lab.core.slippage as slip
    importlib.reload(slip)
    assert slip.haircut_bps() == 12.0


def test_env_malformed_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("SLIPPAGE_HAIRCUT_BPS", "garbage")
    import strategy_lab.core.slippage as slip
    importlib.reload(slip)
    assert slip.haircut_bps() == 8.0


def test_buy_100_at_100_with_8_bps_fills_at_100_08(_reset_env_and_module):
    """Buy 100 shares @ $100 with 8 bps → fill at $100.08."""
    slip = _reset_env_and_module
    # $100 = 10_000 cents. 8 bps → 10_000 * 1.0008 = 10_008 cents = $100.08
    fill = slip.apply_entry_haircut(10_000, "buy")
    assert fill == 10_008


def test_sell_100_at_100_with_8_bps_fills_at_99_92(_reset_env_and_module):
    """Sell 100 shares @ $100 with 8 bps → fill at $99.92."""
    slip = _reset_env_and_module
    # $100 = 10_000 cents. 8 bps → 10_000 * 0.9992 = 9_992 cents = $99.92
    fill = slip.apply_entry_haircut(10_000, "sell")
    assert fill == 9_992


def test_zero_bps_is_noop(monkeypatch):
    monkeypatch.setenv("SLIPPAGE_HAIRCUT_BPS", "0")
    import strategy_lab.core.slippage as slip
    importlib.reload(slip)
    assert slip.apply_entry_haircut(10_000, "buy") == 10_000
    assert slip.apply_entry_haircut(10_000, "sell") == 10_000
    assert slip.apply_exit_haircut(12_345, "buy") == 12_345
    assert slip.apply_exit_haircut(12_345, "sell") == 12_345


def test_integer_cents_rounding(_reset_env_and_module):
    """Sanity: int rounding — e.g. 100.04999 cents → 10005 cents.

    apply_entry_haircut('buy', 10_000) at 5 bps → 10_000 * 1.0005 = 10_005.0
    Rounding behavior on a clean half-cent boundary should round to nearest even
    by Python's default banker's rounding; spec just asks for "sane" int cents.
    """
    os.environ["SLIPPAGE_HAIRCUT_BPS"] = "5"
    import strategy_lab.core.slippage as slip
    importlib.reload(slip)
    fill = slip.apply_entry_haircut(10_000, "buy")
    assert fill == 10_005

    # Edge: 10_001 cents @ 5 bps buy = 10_001 * 1.0005 = 10_006.0005 → 10_006
    fill = slip.apply_entry_haircut(10_001, "buy")
    assert fill == 10_006

    # Cleanup
    del os.environ["SLIPPAGE_HAIRCUT_BPS"]


def test_unknown_side_is_passthrough(_reset_env_and_module):
    slip = _reset_env_and_module
    assert slip.apply_entry_haircut(10_000, "cover") == 10_000
    assert slip.apply_exit_haircut(10_000, "short") == 10_000


def test_exit_haircut_matches_entry_convention(_reset_env_and_module):
    slip = _reset_env_and_module
    assert slip.apply_exit_haircut(10_000, "buy") == slip.apply_entry_haircut(10_000, "buy")
    assert slip.apply_exit_haircut(10_000, "sell") == slip.apply_entry_haircut(10_000, "sell")


def test_round_trip_flat_trade_costs_16_bps_notional(_reset_env_and_module):
    """The big one: buy then sell at the same quote should net to -16 bps notional.

    100 shares quoted at $100 (10_000 cents):
      entry: buy → fill at 10_008 cents (paid 8 bps over quote)
      exit:  sell → fill at 9_992 cents (received 8 bps under quote)
      P&L per share = 9_992 - 10_008 = -16 cents
      Notional ≈ 100 * 10_000 cents = $10,000
      Cost = 100 shares * 16 cents = $16 = 16 bps of $10,000 ✓
    """
    slip = _reset_env_and_module
    qty = 100
    quote_cents = 10_000  # $100

    entry_fill = slip.apply_entry_haircut(quote_cents, "buy")
    exit_fill = slip.apply_exit_haircut(quote_cents, "sell")

    per_share_pnl_cents = exit_fill - entry_fill  # negative for a long
    total_pnl_cents = per_share_pnl_cents * qty
    notional_cents = quote_cents * qty

    # Expected: -16 bps of notional
    expected_cost_cents = -int(round(notional_cents * 16 / 10_000))
    assert total_pnl_cents == expected_cost_cents
    assert total_pnl_cents == -1600  # $16.00 cost on $10k notional


def test_round_trip_short_costs_16_bps_notional(_reset_env_and_module):
    """Short side: sell then cover (buy) at same quote → -16 bps notional."""
    slip = _reset_env_and_module
    qty = 100
    quote_cents = 10_000  # $100

    entry_fill = slip.apply_entry_haircut(quote_cents, "sell")  # short opens
    exit_fill = slip.apply_exit_haircut(quote_cents, "buy")     # cover

    # Short P&L per share = entry - exit
    per_share_pnl_cents = entry_fill - exit_fill
    total_pnl_cents = per_share_pnl_cents * qty
    notional_cents = quote_cents * qty

    expected_cost_cents = -int(round(notional_cents * 16 / 10_000))
    assert total_pnl_cents == expected_cost_cents
    assert total_pnl_cents == -1600


def test_custom_bps_round_trip(monkeypatch):
    """16 bps/side env override → 32 bps round-trip cost."""
    monkeypatch.setenv("SLIPPAGE_HAIRCUT_BPS", "16")
    import strategy_lab.core.slippage as slip
    importlib.reload(slip)

    qty = 100
    quote_cents = 10_000
    entry_fill = slip.apply_entry_haircut(quote_cents, "buy")
    exit_fill = slip.apply_exit_haircut(quote_cents, "sell")

    assert entry_fill == 10_016
    assert exit_fill == 9_984
    total_pnl_cents = (exit_fill - entry_fill) * qty
    assert total_pnl_cents == -3200  # 32 bps of $10k = $32
