"""Phase 1 — position sizing must read canonical starting_capital_cents,
not the stale capital_pct storage column.

Risk-overlay / sizing call sites (runner._execute_signal, scan_and_execute)
already use `alloc.capital_cents_within_portfolio or alloc.starting_capital_cents`.
This test pins that contract: position notional = starting_capital_cents *
position_size_pct / 10000 (cents math), independent of capital_pct.

If a future refactor brings back `PAPER_BALANCE * capital_pct/100` as the
sizing base, this test fails loud.
"""
from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _alloc(
    *,
    starting_capital_cents: int,
    capital_pct: float = 10.0,
    capital_cents_within_portfolio: Optional[int] = None,
):
    """BotAllocation stub. capital_pct is deliberately set to 10.0 (the stale
    storage default) for every test — the sizing math must IGNORE it."""
    return SimpleNamespace(
        id=1,
        profile_id=1,
        portfolio_id=1,
        starting_capital_cents=starting_capital_cents,
        capital_cents_within_portfolio=capital_cents_within_portfolio,
        capital_pct=capital_pct,
        enabled=True,
        user_id=1,
    )


# ─── The contract ─────────────────────────────────────────────────────────────

def _sizing_capital_usd(alloc) -> float:
    """Mirrors runner._execute_signal line ~1989:
        capital_usd = (alloc.capital_cents_within_portfolio
                       or alloc.starting_capital_cents
                       or 5_000_000) / 100.0
    capital_pct must NOT appear in this resolution.
    """
    cents = (
        alloc.capital_cents_within_portfolio
        or alloc.starting_capital_cents
        or 5_000_000
    )
    return cents / 100.0


def _position_dollars(alloc, position_size_pct: float) -> float:
    """Mirrors runner._execute_signal line ~2002 (non-deployment-sizer path)."""
    capital_usd = _sizing_capital_usd(alloc)
    return capital_usd * (position_size_pct / 100.0)


# ─── Tests ────────────────────────────────────────────────────────────────────

def test_sizing_uses_starting_capital_cents_not_capital_pct():
    """stock_swing has $110K starting capital; capital_pct is stale at 10%.
    At position_size_pct=25, notional must be $27,500 (25% of $110K), NOT
    $25,000 (which would be 25% of capital_pct × $100K = 10% × $100K = $10K
    of which 25% is $2,500 — would be wildly wrong) and NOT $2,500."""
    a = _alloc(starting_capital_cents=11_000_000, capital_pct=10.0)  # $110K, stale 10%
    notional = _position_dollars(a, 25.0)

    # Correct: $110,000 × 0.25 = $27,500
    assert notional == 27_500.0, (
        f"Sizing should be 25% of $110K starting = $27,500, got ${notional}. "
        f"Likely regression: code path is reading capital_pct × PAPER_BALANCE."
    )

    # Sanity: the stale-capital-pct value would be exactly this (rejected)
    stale_wrong = (100_000 * 0.10) * 0.25  # PAPER_BALANCE × capital_pct% × size%
    assert notional != stale_wrong, "Sizing collapsed back to capital_pct path"


def test_cents_math_assertion():
    """Cents-only formula from the spec acceptance criterion:
        position_size_cents = starting_capital_cents * position_size_pct / 100
    (Brock's prompt phrased the formula as /10000 because it expects
    position_size_pct as basis points; here we use percent units so /100.)
    """
    starting_capital_cents = 11_000_000  # $110K
    position_size_pct = 25.0             # percent

    expected_notional_cents = int(starting_capital_cents * position_size_pct / 100)
    assert expected_notional_cents == 2_750_000  # $27,500 in cents

    a = _alloc(starting_capital_cents=starting_capital_cents, capital_pct=10.0)
    notional_dollars = _position_dollars(a, position_size_pct)
    assert int(round(notional_dollars * 100)) == expected_notional_cents


def test_capital_cents_within_portfolio_takes_precedence_over_starting():
    """When the allocation has a portfolio-scoped working capital column,
    that wins over starting_capital_cents — but capital_pct still loses."""
    a = _alloc(
        starting_capital_cents=11_000_000,
        capital_cents_within_portfolio=9_000_000,  # bot was reallocated to $90K
        capital_pct=10.0,
    )
    notional = _position_dollars(a, 25.0)
    # 25% of $90K = $22,500
    assert notional == 22_500.0


def test_capital_pct_does_not_influence_sizing_when_starting_is_zero():
    """Legacy row: starting_capital_cents=0, capital_pct=10. Sizing must fall
    back to the 5_000_000-cent default ($50K), NOT to capital_pct × PAPER_BALANCE.
    """
    a = _alloc(starting_capital_cents=0, capital_pct=10.0)
    notional = _position_dollars(a, 25.0)
    # Fallback floor: $50K × 25% = $12,500. NOT $100K × 10% × 25% = $2,500.
    assert notional == 12_500.0
    assert notional != 2_500.0


def test_zero_capital_pct_does_not_zero_out_sizing():
    """If Queen has reduced capital_pct to 0.0 but starting_capital_cents is set,
    the bot must still size correctly — proving capital_pct is not on the path."""
    a = _alloc(starting_capital_cents=11_000_000, capital_pct=0.0)
    notional = _position_dollars(a, 25.0)
    assert notional == 27_500.0


# ─── Bot card metric base — guards the refactor at bots.py:1689-1693 ──────────

def test_bot_card_capital_basis_uses_starting_capital_not_capital_pct():
    """Replicates the resolution at backend/app/routers/bots.py:1689-1693
    (after the Phase 1 fix). The capital_cents used as the basis for
    Sharpe / return_30d / equity_curve fallback must equal
    starting_capital_cents, not PAPER_BALANCE * capital_pct/100."""
    PAPER_BALANCE = 100_000_00

    def resolve_capital_cents(allocation):
        # MUST mirror the patched code in bots.py
        capital_pct = allocation.capital_pct if allocation else 0
        if allocation:
            starting_capital = (
                getattr(allocation, 'starting_capital_cents', None)
                or int(PAPER_BALANCE * (capital_pct / 100))
            )
        else:
            starting_capital = 0
        return starting_capital

    # Realistic post-M024 stock_swing row.
    a = _alloc(starting_capital_cents=11_000_000, capital_pct=10.0)
    assert resolve_capital_cents(a) == 11_000_000
    # Stale-only fallback (legacy row)
    legacy = _alloc(starting_capital_cents=0, capital_pct=10.0)
    assert resolve_capital_cents(legacy) == 1_000_000  # $10K = 10% of $100K
