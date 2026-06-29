"""Tests for SHIP 2 validate_order function behavior.

Tests 6-9 from the spec. Verifies direct registry call semantics for all
asset-class combinations. The per-path wiring (paths 1-12) is enforced by the
gates inserted in the source files and proven by the grep in 02-changes.md.
"""
from __future__ import annotations

import sys
import os
import importlib.util
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_REGISTRY_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "asset_class_registry.py"
))


def _load_registry(discord_send=None):
    fake_discord = types.ModuleType("app.services.discord")
    fake_discord.send_ops_alert = discord_send or (lambda **kw: True)
    old_discord = sys.modules.get("app.services.discord")
    sys.modules["app.services.discord"] = fake_discord

    mod_name = f"_acr_wiring_{id(fake_discord)}"
    sys.modules.pop(mod_name, None)
    spec = importlib.util.spec_from_file_location(mod_name, _REGISTRY_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sys.modules.pop(mod_name, None)

    return mod, old_discord


def _restore(old):
    if old is None:
        sys.modules.pop("app.services.discord", None)
    else:
        sys.modules["app.services.discord"] = old


# ---------------------------------------------------------------------------
# 6. Crypto bot rejected on equity order
# ---------------------------------------------------------------------------

def test_crypto_bot_rejected_on_equity_order():
    reg, old = _load_registry()
    try:
        reg._violation_alert_seen.clear()
        reg._maybe_send_violation_alert = lambda *a, **kw: None

        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order("crypto_quant_scalper", "AAPL")

        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order("crypto_day", "TSLA")

        # Valid crypto calls must NOT raise
        reg.validate_order("crypto_quant_scalper", "BTC/USD")
        reg.validate_order("crypto_day", "ETH/USDT")
    finally:
        _restore(old)


# ---------------------------------------------------------------------------
# 7. cash_floor rejected on non-allowlist ticker
# ---------------------------------------------------------------------------

def test_cash_floor_rejected_on_non_allowlist():
    reg, old = _load_registry()
    try:
        reg._violation_alert_seen.clear()
        reg._maybe_send_violation_alert = lambda *a, **kw: None

        # GOOG is equity but not in allowlist
        with pytest.raises(RuntimeError, match="ticker_not_allowlisted"):
            reg.validate_order("cash_floor", "GOOG")

        with pytest.raises(RuntimeError, match="ticker_not_allowlisted"):
            reg.validate_order("cash_floor", "AAPL")

        # SPY and QQQ must pass
        reg.validate_order("cash_floor", "SPY")
        reg.validate_order("cash_floor", "QQQ")
    finally:
        _restore(old)


# ---------------------------------------------------------------------------
# 8. Options bot rejected on equity order; passes on valid OCC symbol
# ---------------------------------------------------------------------------

def test_options_bot_rejected_on_equity_order():
    reg, old = _load_registry()
    try:
        reg._violation_alert_seen.clear()
        reg._maybe_send_violation_alert = lambda *a, **kw: None

        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order("options_income", "AAPL")

        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order("options_directional", "MSFT")

        # Valid OCC option symbols — must pass
        reg.validate_order("options_income", "SPY  250816P00400000")
        reg.validate_order("options_directional", "SPY250816P00400000")
    finally:
        _restore(old)


# ---------------------------------------------------------------------------
# 9. Equity bot rejected on crypto order
# ---------------------------------------------------------------------------

def test_equity_bot_rejected_on_crypto_order():
    reg, old = _load_registry()
    try:
        reg._violation_alert_seen.clear()
        reg._maybe_send_violation_alert = lambda *a, **kw: None

        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order("stock_swing", "BTC/USD")

        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order("stock_lt", "ETH/USDT")

        # Valid equity calls must NOT raise
        reg.validate_order("stock_swing", "AAPL")
        reg.validate_order("stock_lt", "BRK.B")
    finally:
        _restore(old)
