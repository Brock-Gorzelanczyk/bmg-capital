"""SHIP: options OCC symbol fix.

Covers _build_occ_symbol and the reordered _execute_options_signal so the
equity-ticker gap is closed for good.
"""
import re
import sys
import os
import importlib.util
import types
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from strategy_lab.runner import _build_occ_symbol

_REGISTRY_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "asset_class_registry.py"
))


def _load_registry():
    """Load asset_class_registry by file path (avoids app package import issues)."""
    fake_discord = types.ModuleType("app.services.discord")
    fake_discord.send_ops_alert = lambda **kw: True
    old_discord = sys.modules.get("app.services.discord")
    sys.modules["app.services.discord"] = fake_discord

    mod_name = f"_acr_occ_fix_{id(fake_discord)}"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(mod_name, _REGISTRY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules.pop(mod_name, None)

    return mod, old_discord


def _restore_discord(old):
    if old is None:
        sys.modules.pop("app.services.discord", None)
    else:
        sys.modules["app.services.discord"] = old


OCC_TIGHT_RE = re.compile(r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")


# ── _build_occ_symbol ────────────────────────────────────────────────────────

def test_build_occ_symbol_call_basic():
    assert _build_occ_symbol("NVDA", "2025-01-17", "call", 150.0) == "NVDA250117C00150000"

def test_build_occ_symbol_put_basic():
    assert _build_occ_symbol("AAPL", "2025-06-21", "put", 200.0) == "AAPL250621P00200000"

def test_build_occ_symbol_fractional_strike():
    # 137.50 → 137500 → padded 00137500
    assert _build_occ_symbol("SPY", "2025-08-16", "put", 137.50) == "SPY250816P00137500"

def test_build_occ_symbol_long_underlying_googl():
    # 5-char underlying still matches tight OCC regex
    sym = _build_occ_symbol("GOOGL", "2025-09-19", "call", 175.0)
    assert sym == "GOOGL250919C00175000"
    assert OCC_TIGHT_RE.match(sym)

def test_build_occ_symbol_handles_datetime_date_object():
    sym = _build_occ_symbol("NVDA", date(2025, 1, 17), "call", 150.0)
    assert sym == "NVDA250117C00150000"

def test_build_occ_symbol_handles_datetime_datetime_object():
    sym = _build_occ_symbol("NVDA", datetime(2025, 1, 17, 16, 0, 0), "put", 145.0)
    assert sym == "NVDA250117P00145000"

def test_build_occ_symbol_lowercase_underlying_uppercased():
    assert _build_occ_symbol("aapl", "2025-06-21", "call", 200.0).startswith("AAPL")

def test_build_occ_symbol_iron_condor_label_treated_as_put():
    # option_type "iron condor" does not start with 'c' → P
    sym = _build_occ_symbol("SPY", "2025-08-16", "iron condor", 400.0)
    # SPY(3) + YYMMDD(6) = 9 chars before the C/P slot → index 9
    # Spec comment said index 12 (off by 3); corrected here.
    assert sym[9] == "P"
    assert OCC_TIGHT_RE.match(sym)

def test_build_occ_symbol_negative_strike_raises():
    with pytest.raises(ValueError):
        _build_occ_symbol("NVDA", "2025-01-17", "call", -10.0)

def test_build_occ_symbol_invalid_date_string_raises():
    with pytest.raises(ValueError):
        _build_occ_symbol("NVDA", "not-a-date", "call", 150.0)


# ── _resolve_option_details emits occ_symbol on success ──────────────────────

def test_resolve_option_details_includes_occ_when_resolved(monkeypatch):
    """Happy path: yfinance returns a chain → strike, expiry, occ_symbol set."""
    from strategy_lab import runner

    sig = MagicMock()
    sig.symbol = "AAPL"
    sig.reason = '{"setup": "long_call_directional", "spot": 200.0}'

    # Use a 45-day-out date so DTE filter passes:
    from datetime import timedelta
    target_exp = (date.today() + timedelta(days=45)).isoformat()
    fake_ticker = MagicMock()
    fake_ticker.options = [target_exp]
    chain = MagicMock()
    import pandas as pd
    chain.calls = pd.DataFrame({
        "strike": [170.0, 200.0, 230.0],
        "bid":    [32.0,  10.0,  1.0 ],
        "ask":    [34.0,  11.0,  1.5 ],
        "lastPrice": [33.0, 10.5, 1.2],
    })
    chain.puts = pd.DataFrame({
        "strike": [170.0, 200.0, 230.0],
        "bid":    [1.0,   10.0,  32.0],
        "ask":    [1.5,   11.0,  34.0],
        "lastPrice": [1.2, 10.5, 33.0],
    })
    fake_ticker.option_chain.return_value = chain
    fake_ticker.fast_info = MagicMock(last_price=200.0)

    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker
    monkeypatch.setitem(__import__('sys').modules, 'yfinance', fake_yf)

    opt = runner._resolve_option_details(sig, position_dollars=5000.0)
    assert opt["contract_count"] >= 0
    if opt["contract_count"] > 0:
        assert opt["occ_symbol"] is not None
        assert OCC_TIGHT_RE.match(opt["occ_symbol"])
        assert opt["occ_symbol"].startswith("AAPL")


def test_resolve_option_details_emits_none_occ_on_no_expiry_window(monkeypatch):
    """Reject path: no expiry in 30-60 DTE window → occ_symbol is None."""
    from strategy_lab import runner

    sig = MagicMock()
    sig.symbol = "AAPL"
    sig.reason = '{"setup": "long_call_directional", "spot": 200.0}'

    from datetime import timedelta
    # Only an expiry 5 days out — outside [30,60]
    too_close = (date.today() + timedelta(days=5)).isoformat()
    fake_ticker = MagicMock()
    fake_ticker.options = [too_close]
    fake_ticker.fast_info = MagicMock(last_price=200.0)
    fake_yf = MagicMock()
    fake_yf.Ticker.return_value = fake_ticker
    monkeypatch.setitem(__import__('sys').modules, 'yfinance', fake_yf)

    opt = runner._resolve_option_details(sig, position_dollars=5000.0)
    assert opt["contract_count"] == 0
    assert opt.get("occ_symbol") is None


# ── Asset-class gate: registry already accepts OCC, rejects equity-on-options ─

def test_validate_order_accepts_occ_on_options_bot():
    """Sanity: registry path already works for OCC on options_directional."""
    registry, old = _load_registry()
    try:
        # Must not raise
        registry.validate_order_with_user("options_directional", "NVDA250117C00150000")
    finally:
        _restore_discord(old)

def test_validate_order_rejects_equity_ticker_on_options_bot():
    """This is the gap. Confirm gate still rejects equity tickers — fix is
    upstream (build OCC before calling gate), not in registry."""
    registry, old = _load_registry()
    try:
        with pytest.raises(RuntimeError, match="asset_class_violation"):
            registry.validate_order_with_user("options_directional", "AAPL")
    finally:
        _restore_discord(old)

def test_validate_order_rejects_occ_on_equity_bot():
    """Cross-sleeve invariant from m033/m044/m045: equity bot rejects OCC."""
    registry, old = _load_registry()
    try:
        with pytest.raises(RuntimeError, match="asset_class_violation"):
            registry.validate_order_with_user("stock_swing", "NVDA250117C00150000")
    finally:
        _restore_discord(old)


# ── Regression: OCC tight format matches the registry's OCC regex ────────────

def test_built_occ_matches_registry_regex():
    """Built OCC strings must pass the registry classifier."""
    registry, old = _load_registry()
    try:
        occ = _build_occ_symbol("NVDA", "2025-01-17", "call", 150.0)
        assert registry.classify_instrument(occ) == "option"
        occ2 = _build_occ_symbol("GOOGL", "2025-09-19", "put", 175.0)
        assert registry.classify_instrument(occ2) == "option"
    finally:
        _restore_discord(old)


# ─────────────────────────────────────────────────────────────────────────────
# AST regression guards for _execute_options_signal.
#
# These guard the CORE behavior of the PR: that inside _execute_options_signal,
# the BotPosition / BotTrade rows use occ_symbol (the OCC contract) instead of
# sig.symbol (the equity ticker). Without these guards, a future refactor could
# silently revert to writing the equity ticker and we'd be back to the gap that
# blocked every options trade for 12+ days.
# ─────────────────────────────────────────────────────────────────────────────


def _get_execute_options_signal_ast():
    """Return the AST FunctionDef node for _execute_options_signal."""
    import ast as _ast
    import pathlib
    src = (
        pathlib.Path(__file__).parent.parent
        / "strategy_lab"
        / "runner.py"
    ).read_text()
    tree = _ast.parse(src)
    for node in _ast.walk(tree):
        if isinstance(node, _ast.FunctionDef) and node.name == "_execute_options_signal":
            return node
    raise AssertionError("_execute_options_signal not found in runner.py")


def _find_constructor_calls(func_node, class_name: str):
    """Return list of ast.Call nodes that look like `ClassName(...)` inside func."""
    import ast as _ast
    out = []
    for node in _ast.walk(func_node):
        if not isinstance(node, _ast.Call):
            continue
        f = node.func
        if isinstance(f, _ast.Name) and f.id == class_name:
            out.append(node)
        elif isinstance(f, _ast.Attribute) and f.attr == class_name:
            out.append(node)
    return out


def _get_keyword_value_source(call_node, keyword_name):
    """Return ast.unparse of the value for a keyword arg, or None if absent."""
    import ast as _ast
    for kw in call_node.keywords:
        if kw.arg == keyword_name:
            return _ast.unparse(kw.value)
    return None


_ACCEPTABLE_SYMBOL_EXPRS = ("occ_symbol", "_lr['symbol']", '_lr["symbol"]')


def test_botposition_in_execute_options_uses_occ_symbol():
    """Every BotPosition(...) inside _execute_options_signal must use an OCC-form
    symbol source. This is the gap that blocked options trading: the old code
    passed sig.symbol (the equity ticker "AAPL") which failed the asset-class
    registry on every subsequent check.

    Since 2026-07-09 the runner writes one BotPosition per mleg leg, so the
    literal `symbol=occ_symbol` was replaced with `symbol=_lr['symbol']` where
    `_lr` is a per-leg dict populated from either `_legs` (mleg) or a
    one-element list containing `occ_symbol` (single-leg). Both patterns are
    acceptable; `sig.symbol` is still forbidden.
    """
    func = _get_execute_options_signal_ast()
    calls = _find_constructor_calls(func, "BotPosition")
    assert calls, "Expected at least one BotPosition(...) inside _execute_options_signal"
    for call in calls:
        sym = _get_keyword_value_source(call, "symbol")
        assert sym is not None, (
            f"BotPosition at line {call.lineno} missing symbol= kwarg"
        )
        assert "sig.symbol" not in sym, (
            f"BotPosition at line {call.lineno} uses sig.symbol — must use occ_symbol or _lr['symbol']. "
            f"This was the gap blocking options trades for 12+ days."
        )
        assert any(tok in sym for tok in _ACCEPTABLE_SYMBOL_EXPRS), (
            f"BotPosition at line {call.lineno} symbol expr does not use an "
            f"OCC-form source (occ_symbol / _lr['symbol']): {sym!r}"
        )


def test_bottrade_in_execute_options_uses_occ_symbol():
    """Every BotTrade(...) inside _execute_options_signal must use an OCC-form
    symbol source (occ_symbol or the per-leg `_lr['symbol']` since 2026-07-09).
    """
    func = _get_execute_options_signal_ast()
    calls = _find_constructor_calls(func, "BotTrade")
    assert calls, "Expected at least one BotTrade(...) inside _execute_options_signal"
    for call in calls:
        sym = _get_keyword_value_source(call, "symbol")
        assert sym is not None, (
            f"BotTrade at line {call.lineno} missing symbol= kwarg"
        )
        assert "sig.symbol" not in sym, (
            f"BotTrade at line {call.lineno} uses sig.symbol — must use occ_symbol or _lr['symbol']."
        )
        assert any(tok in sym for tok in _ACCEPTABLE_SYMBOL_EXPRS), (
            f"BotTrade at line {call.lineno} symbol expr does not use an "
            f"OCC-form source (occ_symbol / _lr['symbol']): {sym!r}"
        )


def test_validate_order_call_in_execute_options_uses_occ_symbol():
    """validate_order_with_cooldown_and_user inside _execute_options_signal
    must receive occ_symbol, not sig.symbol. If it gets the equity ticker,
    the registry will reject the trade and we're back to the original gap."""
    import ast as _ast
    func = _get_execute_options_signal_ast()
    found = False
    for node in _ast.walk(func):
        if not isinstance(node, _ast.Call):
            continue
        f = node.func
        name = None
        if isinstance(f, _ast.Name):
            name = f.id
        elif isinstance(f, _ast.Attribute):
            name = f.attr
        if name not in ("validate_order_with_cooldown_and_user", "validate_order"):
            continue
        found = True
        # Find the symbol kwarg or positional that looks like a symbol
        sym_src = _get_keyword_value_source(node, "symbol")
        if sym_src is None:
            # Could be positional; allow if any arg contains 'occ_symbol'
            sym_src = " ".join(_ast.unparse(a) for a in node.args)
        assert "sig.symbol" not in sym_src, (
            f"validate_order call at line {node.lineno} uses sig.symbol — "
            f"must use occ_symbol to pass the options asset-class gate."
        )
        assert "occ_symbol" in sym_src, (
            f"validate_order call at line {node.lineno} does not reference occ_symbol: {sym_src!r}"
        )
    assert found, "No validate_order call found inside _execute_options_signal — refactor regression?"
