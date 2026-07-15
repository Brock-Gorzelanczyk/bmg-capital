"""STOP-THE-LINE tests (2026-07-15) — options risk gates.

Acceptance from Brock: a $12K deep-ITM order MUST get REJECTED with a
logged reason. Prior to this test the per-trade cap gated on premium-at-
risk (small), letting spreads through whose legs marked at $12K+ gross.

Three gates covered:
  1. leg_notional_cap  — single-leg exposure > OPTIONS_MAX_LEG_NOTIONAL_PCT_NAV
  2. per_trade_gross_cap — premium budget > OPTIONS_MAX_PER_TRADE_GROSS_PCT_NAV
  3. dte_floor — DTE < OPTIONS_MIN_DTE

All three fail-open on missing NAV so a diagnostic error can never silence
the fleet — that's the class of failure the observability layer exists
to prevent.
"""
from __future__ import annotations

import os
from unittest.mock import patch


# NAV used for percentage-based caps. Matches the ~$95K fund as of 2026-07-15.
_FAKE_NAV = 95_000.0


# ── Leg-notional gate ────────────────────────────────────────────────────────

def _stub_nav(_db=None):
    return _FAKE_NAV


def test_leg_notional_gate_rejects_12k_deep_itm_spread():
    """The BABA disaster reproduction: 15 contracts of a $111/$112 call spread
    on a $95K fund. Brock's exact acceptance criterion — must reject with a
    logged reason. Under the new caps (max contracts=5 per trade), the
    contracts-per-trade gate fires FIRST, which is fine — the point is
    that this order NEVER submits."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 111.0,
        "occ_symbol": "BABA260828C00111000",
        "legs": [
            {"symbol": "BABA260828C00111000", "side": "buy",  "role": "long_call"},
            {"symbol": "BABA260828C00112000", "side": "sell", "role": "short_call_hedge"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=15)

    assert allowed is False, f"Expected reject, got allowed={allowed}"
    # Under caps-first regime (2026-07-15) the 15-lot fails the contracts
    # cap first. Older behavior would have failed leg_notional_cap. Either
    # rejection reason is acceptable — the point is nothing over 5 contracts
    # ever gets submitted.
    assert (
        "max_contracts_per_trade" in reason
        or "leg_notional_cap" in reason
        or "per_position_notional_cap" in reason
    ), f"Expected caps-related reason, got: {reason}"
    assert "15" in reason or "BABA" in reason, f"Reason must reference the bad input for logging: {reason}"


def test_max_contracts_per_trade_rejects_over_5():
    """Contracts-per-trade gate — cap 5 by default. 6 contracts must reject.

    This is the primary safety knob per Brock's caps spec — the code that
    blocks the BABA-scale disaster at the SIZE dimension regardless of price."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 50.0,
        "occ_symbol": "SPY260828C00050000",
        "legs": [
            {"symbol": "SPY260828C00050000", "side": "buy"},
            {"symbol": "SPY260828C00055000", "side": "sell"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=6)

    assert allowed is False
    assert "max_contracts_per_trade" in reason
    assert "6" in reason and "5" in reason


def test_max_contracts_per_trade_allows_5():
    """The boundary case — exactly 5 contracts is the CAP and must pass.
    Uses a low $10 strike so per-position notional ($10 × 100 × 5 = $5K =
    5.3% NAV) sits well under the 20% cap."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 10.0,
        "occ_symbol": "F260828C00010000",
        "legs": [
            {"symbol": "F260828C00010000", "side": "buy"},
            {"symbol": "F260828C00011000", "side": "sell"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=5)

    assert allowed is True, f"5 contracts × $10 strike = 5% NAV must pass, got reject: {reason}"


def test_sleeve_total_notional_cap_rejects():
    """Sleeve-total cap (Gate C). If current options gross + new trade
    notional exceeds sleeve cap (default 100% NAV), reject with a reason
    that names the sleeve total figure."""
    from strategy_lab.runner import _check_leg_notional_gate

    # 3 contracts × $50 × 100 = $15,000 new notional. Current sleeve = $85K.
    # Together = $100K > 100% NAV ($95K cap).
    opt = {
        "strike_price": 50.0,
        "occ_symbol": "SPY260828C00050000",
        "legs": [
            {"symbol": "SPY260828C00050000", "side": "buy"},
            {"symbol": "SPY260828C00055000", "side": "sell"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 85_000.0):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=3)

    assert allowed is False
    assert "sleeve_total_notional_cap" in reason


def test_leaps_dte_floor_rejects_short_dated():
    """LEAPS DTE floor (Gate D). A "LEAPS" order with 30d DTE isn't a LEAPS.
    Reject with leaps_dte_floor reason. Only fires for strategy=leaps_stock_replacement."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 50.0,
        "occ_symbol": "SPY260828C00050000",
        "expiration_date": "2026-08-14",   # ~30 days from 2026-07-15
        "legs": None,
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_leg_notional_gate(
            opt=opt, contract_count=1, strategy_name="leaps_stock_replacement",
        )

    assert allowed is False
    assert "leaps_dte_floor" in reason


def test_leaps_dte_floor_allows_long_dated_leaps():
    """A real LEAPS with 12mo DTE must pass the LEAPS floor."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 50.0,
        "occ_symbol": "SPY270616C00050000",
        "expiration_date": "2027-06-16",   # ~11 months from 2026-07-15
        "legs": None,
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_leg_notional_gate(
            opt=opt, contract_count=1, strategy_name="leaps_stock_replacement",
        )

    assert allowed is True, f"Real 11-month LEAPS must pass, got reject: {reason}"


def test_leaps_dte_floor_does_not_apply_to_other_strategies():
    """A short-DTE call on a non-LEAPS strategy must pass the LEAPS-specific
    floor (though it may still hit the generic DTE floor in the other gate)."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 50.0,
        "occ_symbol": "SPY260828C00050000",
        "expiration_date": "2026-08-14",
        "legs": None,
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        # Different strategy — LEAPS-specific floor must not fire
        allowed, reason = _check_leg_notional_gate(
            opt=opt, contract_count=1, strategy_name="bull_put_credit_spread",
        )
    assert allowed is True, f"Non-LEAPS strategy must not hit LEAPS floor, got: {reason}"


def test_leg_notional_gate_rejects_deep_itm_meta_call_spread():
    """Today's META $655/$660 spread × 5 contracts on $95K fund.
    Each leg notional = $655 × 100 × 5 = $327,500 = 345% NAV. 5 contracts
    passes the contracts cap but the per-position notional cap catches it."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 655.0,
        "occ_symbol": "META260828C00655000",
        "legs": [
            {"symbol": "META260828C00655000", "side": "buy",  "role": "long_call"},
            {"symbol": "META260828C00660000", "side": "sell", "role": "short_call_hedge"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=5)

    assert allowed is False
    # Under caps-first regime the per_position_notional_cap (Gate B) catches
    # this. Older behavior called the same gate "leg_notional_cap".
    assert "per_position_notional_cap" in reason or "leg_notional_cap" in reason
    assert "META" in reason


def test_leg_notional_gate_allows_reasonable_spread():
    """A modest spread that fits within 20% NAV cap must PASS.
    HPE $42/$43 put spread × 1 contract on $95K fund:
      leg_notional = $42 × 100 × 1 = $4,200 = 4.4% NAV. Passes."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 42.0,
        "occ_symbol": "HPE260821P00042000",
        "legs": [
            {"symbol": "HPE260821P00042000", "side": "buy",  "role": "long_put"},
            {"symbol": "HPE260821P00041000", "side": "sell", "role": "short_put_hedge"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=1)

    assert allowed is True, f"Expected allow, got reject: {reason}"


def test_leg_notional_gate_fails_open_on_missing_nav():
    """If NAV fetch returns None (Alpaca creds missing / down), gate must
    return (True, '') — a diagnostic error must never silence the fleet."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 655.0,
        "occ_symbol": "META260828C00655000",
        "legs": [
            {"symbol": "META260828C00655000", "side": "buy"},
            {"symbol": "META260828C00660000", "side": "sell"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", lambda _db=None: None):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=5)

    assert allowed is True
    assert reason == ""


def test_leg_notional_gate_respects_env_kill_switch():
    """Setting OPTIONS_RISK_GATES_ENABLED=false must bypass this gate."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 655.0,
        "occ_symbol": "META260828C00655000",
        "legs": [
            {"symbol": "META260828C00655000", "side": "buy"},
            {"symbol": "META260828C00660000", "side": "sell"},
        ],
    }
    with patch.dict(os.environ, {"OPTIONS_RISK_GATES_ENABLED": "false"}), \
         patch("strategy_lab.runner._fund_nav_dollars", _stub_nav):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=5)

    assert allowed is True


def test_leg_notional_gate_respects_env_cap_tune():
    """Loosen ALL caps via env → a big trade should pass. Verifies the
    kill-switch pattern of the gate."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 100.0,
        "occ_symbol": "SPY260828C00100000",
        "legs": [
            {"symbol": "SPY260828C00100000", "side": "buy"},
            {"symbol": "SPY260828C00105000", "side": "sell"},
        ],
    }
    with patch.dict(os.environ, {
        "OPTIONS_MAX_LEG_NOTIONAL_PCT_NAV": "5.0",
        "OPTIONS_MAX_NOTIONAL_PCT": "5.0",
        "OPTIONS_SLEEVE_MAX_PCT": "5.0",
        "OPTIONS_MAX_CONTRACTS_PER_TRADE": "100",
    }), patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
       patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=10)

    assert allowed is True, f"Expected allow at fully-loosened caps, got reject: {reason}"


# ── DTE floor gate ───────────────────────────────────────────────────────────

def _sig_with_dte(dte: int):
    class _Sig:
        symbol = "SPY"
        reason = f'{{"setup": "iron_condor_45dte", "dte": {dte}}}'
    return _Sig()


def test_dte_floor_rejects_weekly_gamble():
    """DTE < 7 must be rejected. Default OPTIONS_MIN_DTE=7."""
    from strategy_lab.runner import _check_options_risk_gates

    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_options_risk_gates(
            db=None, profile_name="options_directional",
            sig=_sig_with_dte(3), position_dollars_budget=500.0,
        )

    assert allowed is False
    assert "dte_floor" in reason


def test_dte_floor_allows_45dte():
    """DTE >= 7 (the typical 45-DTE credit spread) must pass."""
    from strategy_lab.runner import _check_options_risk_gates

    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_options_risk_gates(
            db=None, profile_name="options_directional",
            sig=_sig_with_dte(45), position_dollars_budget=500.0,
        )

    assert allowed is True, f"Expected allow, got: {reason}"


# ── Per-trade gross cap ──────────────────────────────────────────────────────

def test_per_trade_cap_rejects_budget_above_pct():
    """A signal budget > 6% NAV must reject.
    6% of $95K = $5,700. Budget $10K must be blocked."""
    from strategy_lab.runner import _check_options_risk_gates

    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 0.0):
        allowed, reason = _check_options_risk_gates(
            db=None, profile_name="options_directional",
            sig=_sig_with_dte(45),
            position_dollars_budget=10_000.0,
        )

    assert allowed is False
    assert "per_trade_gross_cap" in reason


# ── Fleet gross cap ──────────────────────────────────────────────────────────

def test_fleet_gross_cap_rejects_over_100pct():
    """With OPTIONS_GROSS_MAX_PCT_NAV=1.0 default, current options gross
    of $95K + new trade $5K on $95K NAV = 105% — REJECT."""
    from strategy_lab.runner import _check_options_risk_gates

    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav), \
         patch("strategy_lab.runner._current_options_gross_dollars", lambda: 95_000.0):
        allowed, reason = _check_options_risk_gates(
            db=None, profile_name="options_directional",
            sig=_sig_with_dte(45),
            position_dollars_budget=5_000.0,
        )

    assert allowed is False
    assert "fleet_options_gross_cap" in reason
