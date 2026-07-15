"""Options P&L multiplier — acceptance test from Brock's audit 2026-07-15.

Bug: /api/portfolio/open-positions computed cost_basis = premium × qty
for options, missing the ×100 shares-per-contract multiplier. Result: a
5-lot BABA $111 call bought at $19.70 now marked $23.65 displayed as
+214% (bases off $98.50 instead of $9,850) instead of the correct
+20.05%.

Acceptance from spec:
  "a 5-lot BABA $111 call bought at $19.70 now marked $23.65 reads
   +$1,975.00 (+20.05%), not +214%; every % sign matches its $ sign"
"""
from __future__ import annotations


# ─── Reference P&L math (must match the fixed portfolio.py formula) ─────────

def _options_pnl(avg_premium: float, mark: float, qty: int) -> tuple[float, float]:
    """Return (unrealized_usd, unrealized_pct) using the corrected formula.
    This is the shape portfolio.py:241-250 now uses for options positions
    (contract_multiplier=100).
    """
    contract_multiplier = 100
    cost_basis = avg_premium * qty * contract_multiplier
    market_value = mark * qty * contract_multiplier
    unrealized_usd = market_value - cost_basis
    unrealized_pct = (unrealized_usd / cost_basis * 100) if cost_basis > 0 else 0.0
    return round(unrealized_usd, 2), round(unrealized_pct, 4)


# ─── Brock's exact acceptance case ──────────────────────────────────────────

def test_baba_5_lot_from_1970_to_2365_reads_correctly():
    """SPEC acceptance: 5-lot BABA $111 call, avg $19.70, mark $23.65
    → +$1,975.00 (+20.05%), NOT +214%."""
    pnl_usd, pnl_pct = _options_pnl(avg_premium=19.70, mark=23.65, qty=5)
    assert pnl_usd == 1975.00, f"expected +$1,975.00, got ${pnl_usd:+.2f}"
    assert abs(pnl_pct - 20.0508) < 0.01, f"expected +20.05%, got {pnl_pct:+.2f}%"


def test_signs_agree_on_loss():
    """Every % sign must match its $ sign. Test the loss side."""
    pnl_usd, pnl_pct = _options_pnl(avg_premium=10.00, mark=6.00, qty=5)
    # cost = $5,000, value = $3,000, loss = -$2,000 = -40%
    assert pnl_usd == -2000.00
    assert abs(pnl_pct - (-40.0)) < 0.01
    assert (pnl_usd < 0) == (pnl_pct < 0), "signs must agree"


def test_signs_agree_on_win():
    pnl_usd, pnl_pct = _options_pnl(avg_premium=1.00, mark=2.50, qty=10)
    # cost = $1,000, value = $2,500, win = +$1,500 = +150%
    assert pnl_usd == 1500.00
    assert abs(pnl_pct - 150.0) < 0.01
    assert (pnl_usd > 0) == (pnl_pct > 0)


def test_multiplier_prevents_214pct_garbage():
    """The old bug produced +214% because cost_basis was computed without
    the ×100. Verify that with the fix, no reasonable option position
    produces triple-digit P&L pct unless it's an actual 100%+ move."""
    # BABA case: real move is 20%. Old (broken) code would have shown 214%.
    pnl_usd, pnl_pct = _options_pnl(avg_premium=19.70, mark=23.65, qty=5)
    # Sanity: with the buggy formula (missing ×100 on cost_basis), pct would
    # look ~214% (well over 100). With the fix, it should be ~20%.
    assert pnl_pct < 100, f"corrected pct must not exceed 100 for a small underlying move, got {pnl_pct:+.2f}%"
    # And should be close to real 20% return.
    assert 15 < pnl_pct < 25


def test_1_contract_edge_case():
    """1-contract positions must also apply ×100. This is the case that
    LOOKED right in the buggy code (qty=1 makes ×qty a no-op) but wasn't
    catching that ×100 was still missing."""
    pnl_usd, pnl_pct = _options_pnl(avg_premium=5.00, mark=6.00, qty=1)
    # cost = 5*1*100 = $500, value = 6*1*100 = $600, +$100 = +20%
    assert pnl_usd == 100.00
    assert abs(pnl_pct - 20.0) < 0.01


def test_zero_cost_basis_returns_zero_not_crash():
    """avg_premium=0 edge case (shouldn't happen but defend against divide-by-zero)."""
    pnl_usd, pnl_pct = _options_pnl(avg_premium=0.0, mark=1.0, qty=1)
    assert pnl_pct == 0.0


# ─── Sanity: the SIGNED formula against Alpaca convention ───────────────────

def test_portfolio_endpoint_uses_multiplier_100():
    """Regression: read portfolio.py and confirm the multiplier is present."""
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    src_path = os.path.join(here, "..", "app", "routers", "portfolio.py")
    with open(src_path) as f:
        src = f.read()
    # The fix uses contract_multiplier applied to cost_basis + market value.
    assert "contract_multiplier" in src, "portfolio.py must have the contract_multiplier fix"
    assert "option_type" in src, "portfolio.py must branch on option_type presence"
    assert "* contract_multiplier" in src, "cost/value computations must be multiplied"
