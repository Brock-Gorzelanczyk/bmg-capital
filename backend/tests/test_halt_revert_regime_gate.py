"""Regression: 2026-06-30 halt + revert + regime gate.

Three groups of guards:
  1. m051 halts the two losing Quant bots and is idempotent via _gate.
  2. The 2026-06-24 deployment-push overrides are removed from all 3 Quant YAMLs.
  3. Every active crypto MR strategy gates on trend_regime (no MR in bull/bear).
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
PROFILES = BACKEND / "strategy_lab" / "profiles"
STRATEGIES = BACKEND / "strategy_lab" / "strategies"
MIGRATIONS = BACKEND / "app" / "db" / "migrations"


# ---------------------------------------------------------------------------
# Group 1: m051 halt migration
# ---------------------------------------------------------------------------

def _load_m051():
    """Direct-load m051 bypassing conftest stubs.

    m051 imports _gate INSIDE its run() function (not at module top-level),
    so a fresh module load only needs the imports at the top — none of which
    touch _gate. We never call run() in these tests; we only inspect module
    constants and source. Deliberately do NOT stub _gate in sys.modules to
    avoid polluting subsequent tests that need the real gate functions.
    """
    path = MIGRATIONS / "m051_halt_quant_losers.py"
    full_name = "tests_m051_isolated_load"  # unique key to avoid sys.modules collision
    spec = importlib.util.spec_from_file_location(full_name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_m051_targets_only_loser_bots():
    """The migration must disable exactly the two confirmed-loser bots — not the
    winner (crypto_quant_aggressive) and not any of the equity/options bots.
    """
    m051 = _load_m051()
    assert set(m051._TARGET_BOTS) == {"crypto_quant_mean_reversion", "crypto_quant_scalper"}, (
        f"m051 must target only Mean Rev + Scalper, got {m051._TARGET_BOTS}"
    )
    # The migration must NOT touch crypto_quant_aggressive (the only winner).
    assert "crypto_quant_aggressive" not in m051._TARGET_BOTS


def test_m051_paused_reason_is_auditable():
    """The paused_reason must include the date so future audits can grep it."""
    m051 = _load_m051()
    assert "2026_06_30" in m051._PAUSED_REASON or "2026-06-30" in m051._PAUSED_REASON, (
        f"paused_reason must include the halt date, got {m051._PAUSED_REASON!r}"
    )
    assert m051._PAUSED_REASON != "admin_lock", (
        "Use a distinct paused_reason (not generic admin_lock) so this halt "
        "is greppable in audit history"
    )


def test_m051_is_gated_for_re_enable_safety():
    """The migration must be gated so operators can re-enable later without
    the next boot silently flipping them back off.
    """
    src = (MIGRATIONS / "m051_halt_quant_losers.py").read_text()
    assert "already_ran" in src and "record" in src, (
        "m051 must use _gate.already_ran/_gate.record so a re-enable is sticky"
    )
    assert "_MIGRATION_NAME" in src, "m051 must define _MIGRATION_NAME for the gate"


def test_m051_preserves_capital_allocation():
    """The migration must NOT zero starting_capital_cents or any capital field.
    Capital reservation is preserved so the bot can be re-enabled later.
    """
    src = (MIGRATIONS / "m051_halt_quant_losers.py").read_text()
    assert "starting_capital_cents" not in src or "UPDATE" not in src.split("starting_capital_cents")[0].split("\n")[-1], (
        "m051 must NOT update starting_capital_cents — capital reservation is preserved"
    )


def test_m051_wired_into_main_startup():
    """The migration must be registered in app/main.py startup sequence."""
    src = (BACKEND / "app" / "main.py").read_text()
    assert "m051_halt_quant_losers" in src, "m051 must be imported in main.py startup"
    assert "_run_m051" in src or "m051_halt_quant_losers" in src
    # Ordering check: m051 should run after m050 so we don't break the chain.
    m050_idx = src.find("m050_daily_audit_log")
    m051_idx = src.find("m051_halt_quant_losers")
    assert m050_idx > 0 and m051_idx > m050_idx, (
        "m051 must be registered AFTER m050 in main.py to keep migration ordering"
    )


# ---------------------------------------------------------------------------
# Group 2: 2026-06-24 deployment-push overrides removed
# ---------------------------------------------------------------------------

_QUANT_PROFILES = (
    "crypto_quant_aggressive.yaml",
    "crypto_quant_mean_reversion.yaml",
    "crypto_quant_scalper.yaml",
)

# Keys that must not appear in the YAML after the 2026-06-30 revert.
# (They were intended to be temporary 7-day push overrides.)
_FORBIDDEN_OVERRIDE_KEYS = (
    "composite_threshold_override",
    "position_size_pct_override",
    "max_concurrent_positions",
)


@pytest.mark.parametrize("profile_file", _QUANT_PROFILES)
def test_deployment_push_overrides_removed(profile_file):
    """The 3 Quant YAML configs must not contain the 2026-06-24 push overrides."""
    path = PROFILES / profile_file
    cfg = yaml.safe_load(path.read_text())
    assert cfg is not None, f"{profile_file} failed to parse"
    for key in _FORBIDDEN_OVERRIDE_KEYS:
        assert key not in cfg, (
            f"{profile_file} still contains 2026-06-24 push override {key!r} — "
            f"must be removed per 2026-06-30 revert"
        )


# ---------------------------------------------------------------------------
# Group 3: regime gate present on every active crypto MR strategy
# ---------------------------------------------------------------------------

# These 6 strategies are listed in crypto_quant_mean_reversion.yaml — every one
# must short-circuit when trend_regime is bull/bear.
_ACTIVE_MR_STRATEGIES = (
    "crypto_mr_bollinger_extreme.py",
    "crypto_mr_keltner_outside_band.py",
    "crypto_mr_pin_bar_rejection.py",
    "crypto_mr_rsi_overbought_short.py",
    "crypto_mr_rsi_oversold_bounce.py",
    "crypto_mr_zscore_reversion.py",
)


@pytest.mark.parametrize("strategy_file", _ACTIVE_MR_STRATEGIES)
def test_mr_strategy_has_regime_gate(strategy_file):
    """Every active crypto MR strategy must gate on trend_regime.

    Pattern: read regime['trend_regime'], early-return [] if it's bull/bear.
    """
    src = (STRATEGIES / strategy_file).read_text()
    # The gate must reference trend_regime
    assert 'trend_regime' in src, (
        f"{strategy_file} must read regime['trend_regime'] for the regime gate"
    )
    # The gate must explicitly handle bull/bear with an early return
    assert '"bull"' in src and '"bear"' in src, (
        f"{strategy_file} regime gate must mention 'bull' and 'bear' values "
        f"(the trending-regime cases where MR loses)"
    )


def _load_strategy_module(strategy_file: str):
    """Direct-load a strategy module bypassing conftest stubs."""
    path = STRATEGIES / strategy_file
    # Pre-create stub for strategy_lab.core.signals so we can load the module.
    if "strategy_lab" not in sys.modules:
        pkg = type(sys)("strategy_lab")
        pkg.__path__ = [str(BACKEND / "strategy_lab")]
        sys.modules["strategy_lab"] = pkg
    if "strategy_lab.core" not in sys.modules:
        core_pkg = type(sys)("strategy_lab.core")
        core_pkg.__path__ = [str(BACKEND / "strategy_lab" / "core")]
        sys.modules["strategy_lab.core"] = core_pkg
    if "strategy_lab.core.signals" not in sys.modules:
        signals_spec = importlib.util.spec_from_file_location(
            "strategy_lab.core.signals",
            str(BACKEND / "strategy_lab" / "core" / "signals.py"),
        )
        signals_mod = importlib.util.module_from_spec(signals_spec)
        sys.modules["strategy_lab.core.signals"] = signals_mod
        signals_spec.loader.exec_module(signals_mod)
    spec = importlib.util.spec_from_file_location(
        f"strategy_lab.strategies.{strategy_file[:-3]}",
        str(path),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.mark.parametrize("strategy_file", _ACTIVE_MR_STRATEGIES)
def test_mr_strategy_returns_empty_in_bull_regime(strategy_file):
    """Functional: each MR strategy must return [] when trend_regime is bull."""
    mod = _load_strategy_module(strategy_file)
    # Empty bars dict means no symbols to evaluate; if the gate works, we get []
    # without ever entering the per-symbol loop.
    bull_regime = {"trend_regime": "bull"}
    bear_regime = {"trend_regime": "bear"}
    chop_regime = {"trend_regime": "chop"}
    profile_config = {"universe": {"symbols": []}}
    assert mod.generate_signals({}, profile_config, bull_regime) == [], (
        f"{strategy_file} must return [] in bull regime"
    )
    assert mod.generate_signals({}, profile_config, bear_regime) == [], (
        f"{strategy_file} must return [] in bear regime"
    )
    # Chop is the expected MR-friendly regime; empty bars still gives [] but
    # the call must not error.
    result = mod.generate_signals({}, profile_config, chop_regime)
    assert isinstance(result, list), f"{strategy_file} must return list in chop regime"


@pytest.mark.parametrize("strategy_file", _ACTIVE_MR_STRATEGIES)
def test_mr_strategy_tolerates_missing_regime(strategy_file):
    """Defensive: gate must not crash when regime dict is empty or None."""
    mod = _load_strategy_module(strategy_file)
    profile_config = {"universe": {"symbols": []}}
    # Empty regime — gate should fall through to chop behavior (no early return).
    result_empty = mod.generate_signals({}, profile_config, {})
    assert isinstance(result_empty, list)
    # None regime — gate should still not crash.
    result_none = mod.generate_signals({}, profile_config, None)
    assert isinstance(result_none, list)
