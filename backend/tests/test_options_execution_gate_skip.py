"""Regression: options-class profiles must bypass the equity asset-class gate
in `_execute_signal` so the signal can reach `_execute_options_signal`.

2026-06-30 incident: Options Income fired AAPL cash_secured_put @ conf 0.87
and Options Directional fired AMD leaps_stock_replacement @ conf 0.84 (both
during the 14:00 UTC market-open scan window), but trades_24h stayed at 0 for
both bots. Root cause: `_execute_signal` runs the asset-class gate BEFORE the
routing branch that calls `_execute_options_signal`. The gate validates
`sig.symbol` (the underlying equity ticker, e.g. "AAPL") against the bot's
required asset class ("option" per the registry). equity != option → silent
RuntimeError → early return. The signal never reached the options path.

Fix: skip the gate at this call site when `profile.asset_class == "options"`.
The options-specific path runs the same gate with the resolved OCC contract
symbol, which is the correct check.

These guards lock the fix structurally.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"


def test_execute_signal_skips_equity_gate_for_options_profiles():
    """The pre-route gate in `_execute_signal` must be wrapped in an
    `if profile.asset_class != "options"` guard so options signals can flow
    through to `_execute_options_signal` without being blocked on the
    underlying equity ticker.
    """
    src = (BACKEND / "strategy_lab" / "runner.py").read_text()
    # Locate the validate_order_with_cooldown_and_user call inside _execute_signal.
    # There are TWO call sites: one in _execute_signal (the equity path) and one
    # inside _execute_options_signal (the options path). The fix is only on the
    # first one. Both must remain present.
    calls = list(re.finditer(
        r"validate_order_with_cooldown_and_user\(",
        src,
    ))
    assert len(calls) >= 2, (
        f"Expected at least 2 validate_order_with_cooldown_and_user call sites "
        f"(one in _execute_signal, one in _execute_options_signal); found {len(calls)}"
    )

    # Locate the call inside _execute_signal specifically (the equity path).
    # Source order is _execute_options_signal first, then _execute_signal —
    # find the def of _execute_signal and look for the first call after it.
    es_def = src.find("def _execute_signal(")
    assert es_def > 0, "Could not locate _execute_signal definition"
    call_in_es = src.find("validate_order_with_cooldown_and_user(", es_def)
    assert call_in_es > 0, (
        "_execute_signal has no validate_order_with_cooldown_and_user call — "
        "either the gate was removed entirely (security regression) or the "
        "function signature changed"
    )
    # The call must be guarded by a check that profile.asset_class != "options".
    # Look in a window before the call.
    window = src[es_def:call_in_es]
    assert (
        'asset_class' in window and '"options"' in window
    ), (
        "validate_order_with_cooldown_and_user call inside _execute_signal must "
        "be guarded by an `if profile.asset_class != 'options'` check so options "
        "signals reach the options router. Regression of 2026-06-30 fix."
    )


def test_options_execute_path_still_validates_occ_contract():
    """Defensive: `_execute_options_signal` must STILL call
    validate_order_with_cooldown_and_user with the OCC contract symbol. The
    fix only skips the equity-gate at the pre-route call site; it does NOT
    skip validation entirely.
    """
    src = (BACKEND / "strategy_lab" / "runner.py").read_text()
    # Look for the options-path call: occ_symbol must be the symbol argument.
    options_section_start = src.find("def _execute_options_signal")
    assert options_section_start > 0, "Could not locate _execute_options_signal"
    options_section_end = src.find("\ndef ", options_section_start + 1)
    options_section = src[options_section_start:options_section_end]
    assert "validate_order_with_cooldown_and_user" in options_section, (
        "_execute_options_signal must still call validate_order_with_cooldown_and_user "
        "(with the OCC contract symbol) so options orders are validated"
    )
    assert "symbol=occ_symbol" in options_section, (
        "_execute_options_signal's gate call must pass symbol=occ_symbol "
        "(the resolved contract), not the underlying ticker"
    )


def test_pre_route_gate_still_runs_for_equity_profiles():
    """Equity-class profiles (stock_*, crypto_*) must still hit the pre-route
    gate. The guard must be a NEGATIVE check (`!= "options"`), not an
    elimination of the gate entirely.
    """
    src = (BACKEND / "strategy_lab" / "runner.py").read_text()
    # Look for the negative check pattern in the runner.
    assert (
        '!= "options"' in src or "!= 'options'" in src
    ), (
        "Pre-route gate must be guarded by an inequality check against "
        "'options' so equity/crypto profiles still get validated"
    )
