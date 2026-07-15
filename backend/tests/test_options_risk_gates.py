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
    on a $95K fund. Each leg's notional = $111 × 100 × 15 = $166,500 ≈ 175% NAV.
    Must reject with reason containing 'leg_notional_cap'."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 111.0,
        "occ_symbol": "BABA260828C00111000",
        "legs": [
            {"symbol": "BABA260828C00111000", "side": "buy",  "role": "long_call"},
            {"symbol": "BABA260828C00112000", "side": "sell", "role": "short_call_hedge"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=15)

    assert allowed is False, f"Expected reject, got allowed={allowed}"
    assert "leg_notional_cap" in reason, f"Expected leg_notional_cap in reason, got: {reason}"
    assert "BABA" in reason, f"Expected symbol in reason for logging clarity, got: {reason}"


def test_leg_notional_gate_rejects_deep_itm_meta_call_spread():
    """Today's META $655/$660 spread × 5 contracts on $95K fund.
    Each leg notional = $655 × 100 × 5 = $327,500 = 345% NAV.
    Must reject with reason containing 'leg_notional_cap'."""
    from strategy_lab.runner import _check_leg_notional_gate

    opt = {
        "strike_price": 655.0,
        "occ_symbol": "META260828C00655000",
        "legs": [
            {"symbol": "META260828C00655000", "side": "buy",  "role": "long_call"},
            {"symbol": "META260828C00660000", "side": "sell", "role": "short_call_hedge"},
        ],
    }
    with patch("strategy_lab.runner._fund_nav_dollars", _stub_nav):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=5)

    assert allowed is False
    assert "leg_notional_cap" in reason
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
    """A very high cap (100% NAV) lets a large but not extreme trade through."""
    from strategy_lab.runner import _check_leg_notional_gate

    # 10 contracts of $100 strike = $100,000 = 105% NAV — normally reject
    opt = {
        "strike_price": 100.0,
        "occ_symbol": "SPY260828C00100000",
        "legs": [
            {"symbol": "SPY260828C00100000", "side": "buy"},
            {"symbol": "SPY260828C00105000", "side": "sell"},
        ],
    }
    # With cap loosened to 200% NAV, it passes
    with patch.dict(os.environ, {"OPTIONS_MAX_LEG_NOTIONAL_PCT_NAV": "2.0"}), \
         patch("strategy_lab.runner._fund_nav_dollars", _stub_nav):
        allowed, reason = _check_leg_notional_gate(opt=opt, contract_count=10)

    assert allowed is True, f"Expected allow at 200% cap, got reject: {reason}"


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
