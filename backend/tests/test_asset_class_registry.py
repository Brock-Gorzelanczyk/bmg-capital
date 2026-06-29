"""Tests for backend/app/services/asset_class_registry.py — SHIP 2."""
from __future__ import annotations

import sys
import os
import importlib.util
import importlib
import logging
import types

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_REGISTRY_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "app", "services", "asset_class_registry.py"
))


def _load_registry(discord_send=None):
    """Load the registry from file, pre-injecting a fake discord module.

    Returns the loaded module. The fake discord stays in sys.modules for the
    lifetime of the returned module's function calls (rate-limit dict, etc.).

    Call _restore_discord(old) after the test to clean up.
    Returns (registry_mod, old_discord_mod).
    """
    fake_discord = types.ModuleType("app.services.discord")
    fake_discord.send_ops_alert = discord_send or (lambda **kw: True)
    old_discord = sys.modules.get("app.services.discord")
    sys.modules["app.services.discord"] = fake_discord

    mod_name = f"_acr_test_{id(fake_discord)}"
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


# ---------------------------------------------------------------------------
# 1. Registry covers all m027 bots
# ---------------------------------------------------------------------------

def test_registry_covers_all_m027_bots():
    reg, old = _load_registry()
    try:
        M027_BOTS = {
            "stock_swing", "stock_lt", "stock_day",
            "crypto_day", "crypto_swing", "crypto_lt", "crypto_onchain",
            "options_income", "options_directional",
            "crypto_quant_aggressive", "crypto_quant_mean_reversion",
            "crypto_quant_scalper",
            "cash_floor",
        }
        M027_CENTS = {
            "stock_swing":                  11_000_000,
            "stock_lt":                      9_000_000,
            "stock_day":                     7_000_000,
            "crypto_day":                    9_000_000,
            "crypto_swing":                  7_000_000,
            "crypto_lt":                     6_000_000,
            "crypto_onchain":                5_000_000,
            "options_income":                5_000_000,
            "options_directional":           5_000_000,
            "crypto_quant_aggressive":      11_000_000,
            "crypto_quant_mean_reversion":   8_000_000,
            "crypto_quant_scalper":          7_000_000,
            "cash_floor":                   10_000_000,
        }
        for bot in M027_BOTS:
            assert bot in reg.ASSET_CLASS_REGISTRY, f"{bot} missing from registry"
        assert sum(M027_CENTS.values()) == 100_000_000
    finally:
        _restore_discord(old)


# ---------------------------------------------------------------------------
# 2. classify_instrument edge cases
# ---------------------------------------------------------------------------

def test_classify_instrument_handles_edge_cases():
    reg, old = _load_registry()
    try:
        ci = reg.classify_instrument

        assert ci("BRK.B") == "equity"
        assert ci("BTC/USD") == "crypto"
        assert ci("ETH/USDC") == "crypto"
        assert ci("SOL/USDT") == "crypto"
        assert ci("SPY  250816P00400000") == "option"
        assert ci("SPY250816P00400000") == "option"

        with pytest.raises(RuntimeError, match="unclassifiable"):
            ci("")
        with pytest.raises(RuntimeError, match="unclassifiable"):
            ci("foo bar")
        with pytest.raises(RuntimeError, match="unclassifiable"):
            ci("123")
    finally:
        _restore_discord(old)


# ---------------------------------------------------------------------------
# 3. Spec-slug aliases raise with canonical name
# ---------------------------------------------------------------------------

def test_spec_slug_aliases_raise_with_canonical_name():
    reg, old = _load_registry()
    try:
        with pytest.raises(RuntimeError) as exc:
            reg.get_required_asset_class("quant_mean_rev")
        assert "crypto_quant_mean_reversion" in str(exc.value)

        with pytest.raises(RuntimeError) as exc:
            reg.get_required_asset_class("quant_scalper")
        assert "crypto_quant_scalper" in str(exc.value)

        with pytest.raises(RuntimeError) as exc:
            reg.get_required_asset_class("stock_long_term")
        assert "stock_lt" in str(exc.value)

        with pytest.raises(RuntimeError) as exc:
            reg.get_required_asset_class("crypto_lt_dca")
        assert "crypto_lt" in str(exc.value)
    finally:
        _restore_discord(old)


# ---------------------------------------------------------------------------
# 4. validate_order logs violation with required and detected fields
# ---------------------------------------------------------------------------

def test_validate_order_logs_violation_with_required_and_detected_fields(caplog):
    reg, old = _load_registry()
    try:
        reg._violation_alert_seen.clear()
        # Suppress the actual discord call so only the log matters
        reg._maybe_send_violation_alert = lambda *a, **kw: None

        with caplog.at_level(logging.WARNING, logger=reg.__name__):
            with pytest.raises(RuntimeError, match="asset_class_violation"):
                reg.validate_order_with_user(
                    bot_id="crypto_quant_scalper",
                    symbol="AAPL",
                    user_id=1,
                )

        assert any(
            "asset_class_violation" in r.message
            and "crypto_quant_scalper" in r.message
            and "AAPL" in r.message
            and "required=crypto" in r.message
            and "detected=equity" in r.message
            for r in caplog.records
        ), f"Log not found. Records: {[r.message for r in caplog.records]}"
    finally:
        _restore_discord(old)


# ---------------------------------------------------------------------------
# 5. Rate-limit: Discord alert fires once per (bot, symbol) per UTC day
# ---------------------------------------------------------------------------

def test_validate_order_rate_limits_discord_to_once_per_bot_symbol_per_day():
    alert_calls: list = []

    def _fake_send(**kwargs):
        alert_calls.append(kwargs)
        return True

    reg, old = _load_registry(discord_send=_fake_send)
    try:
        reg._violation_alert_seen.clear()

        # 5 calls same (bot, symbol) same UTC day -> 1 alert
        for _ in range(5):
            try:
                reg.validate_order("crypto_quant_scalper", "AAPL")
            except RuntimeError:
                pass

        assert len(alert_calls) == 1, f"Expected 1 alert, got {len(alert_calls)}"

        # Simulate day rollover: clear the dict entry for today
        import datetime
        today = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        key = ("crypto_quant_scalper", "AAPL", today)
        reg._violation_alert_seen.pop(key, None)

        # Next call -> second alert
        try:
            reg.validate_order("crypto_quant_scalper", "AAPL")
        except RuntimeError:
            pass

        assert len(alert_calls) == 2, f"Expected 2 alerts after reset, got {len(alert_calls)}"
    finally:
        _restore_discord(old)


# ---------------------------------------------------------------------------
# Edge case: None symbol passed to classify_instrument
# ---------------------------------------------------------------------------

def test_classify_instrument_none_symbol_raises():
    reg, old = _load_registry()
    try:
        with pytest.raises((RuntimeError, AttributeError)):
            # None should never silently pass; either raises RuntimeError (our
            # guard) or AttributeError on .strip() — both are correct failure modes.
            reg.classify_instrument(None)
    finally:
        _restore_discord(old)


# ---------------------------------------------------------------------------
# Edge case: Unknown bot_id raises with helpful message
# ---------------------------------------------------------------------------

def test_unknown_bot_id_raises_with_message():
    reg, old = _load_registry()
    try:
        with pytest.raises(RuntimeError) as exc:
            reg.get_required_asset_class("crypto_meanrev_2163")
        assert "unknown bot_id" in str(exc.value), (
            f"Error message should mention 'unknown bot_id', got: {exc.value}"
        )

        # validate_order must also raise for unknown bot_id
        with pytest.raises(RuntimeError):
            reg.validate_order("retired_bot_xyz", "AAPL")
    finally:
        _restore_discord(old)


# ---------------------------------------------------------------------------
# Edge case: Multi-user isolation — validate_order fires regardless of user_id
# ---------------------------------------------------------------------------

def test_validate_order_fires_for_any_user():
    """Gate must fire for user_id=1 AND user_id=3 equally (user-agnostic)."""
    reg, old = _load_registry()
    try:
        reg._violation_alert_seen.clear()
        reg._maybe_send_violation_alert = lambda *a, **kw: None

        # user_id=1 — must raise
        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order_with_user("crypto_quant_scalper", "AAPL", user_id=1)

        # user_id=3 — must also raise (gate is user-agnostic)
        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order_with_user("crypto_quant_scalper", "AAPL", user_id=3)

        # user_id=None — must also raise
        with pytest.raises(RuntimeError, match="asset_class_violation"):
            reg.validate_order_with_user("crypto_quant_scalper", "AAPL", user_id=None)
    finally:
        _restore_discord(old)
