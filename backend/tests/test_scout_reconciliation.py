"""SHIP 4 reconciliation tests — Strategy Scout listing must equal Past Triggers.

The Scout quick-lookup listing previously called `_simulate_strategy_on_bars`
(2y, hold=15d, walk-forward via live signal generator) while the Past Triggers
panel called `run_backtest` (5y, hold=30d, strategy-specific detectors).
Different windows + different hold + different signal source → wildly
different Sharpe / Win / Avg Return numbers for the SAME (symbol, strategy).

This is the "portfolio split-brain" pattern from vault/known-issues #1 applied
to the Scout surface. Fixed by routing both surfaces through a single
canonical function (`run_backtest`) with the same parameters.

Tests assert:
  1. Listing helper calls produce identical numbers to direct run_backtest
     calls for the 5 named symbols × representative strategies, within the
     spec tolerances (Sharpe ±0.1, win ±1%, avg_return ±0.1%, triggers exact).
  2. Min-sample filter excludes strategies with <20 triggers.
  3. Listing helper returns the new avg_return_pct field on its payload.

The tests use synthetic bar series — they do NOT hit yfinance — so they run
deterministically in CI.
"""
from __future__ import annotations

import importlib.util
import math
import os
import random
import sys

import pytest

# conftest.py stubs out `app` at the module level so tests that import
# DB-bound code can run without a live database. That stubbing makes a normal
# `from app.routers.scout import ...` impossible. We bypass it by loading the
# specific source files we need directly via importlib.spec_from_file_location.
_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_module_from_path(module_name: str, rel_path: str):
    abs_path = os.path.join(_BACKEND_ROOT, rel_path)
    spec = importlib.util.spec_from_file_location(module_name, abs_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {module_name} from {abs_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


# Load strategy_backtest first — scout depends on it at call time.
_strategy_backtest = _load_module_from_path(
    "_ship4_strategy_backtest",
    "app/services/strategy_backtest.py",
)
run_backtest = _strategy_backtest.run_backtest

# Register under the import path scout.py expects so its lazy
# `from app.services.strategy_backtest import run_backtest` finds the same
# module object inside _reconciled_stats_for_strategy.
sys.modules["app.services.strategy_backtest"] = _strategy_backtest

# scout.py imports several app-level symbols at module-load time that
# conftest doesn't stub. Patch them in before exec.
from unittest.mock import MagicMock as _MM

_db_session_stub = sys.modules.get("app.db.session")
if _db_session_stub is not None and not hasattr(_db_session_stub, "get_db"):
    _db_session_stub.get_db = _MM(name="get_db")

# app.dependencies (for get_current_user)
import types as _types
if "app.dependencies" not in sys.modules:
    _dep_stub = _types.ModuleType("app.dependencies")
    _dep_stub.get_current_user = _MM(name="get_current_user")
    sys.modules["app.dependencies"] = _dep_stub
    _app_mod = sys.modules.get("app")
    if _app_mod is not None:
        _app_mod.dependencies = _dep_stub

# Now load scout itself.
_scout = _load_module_from_path("_ship4_scout", "app/routers/scout.py")

_LISTING_HOLD_DAYS = _scout._LISTING_HOLD_DAYS
_LISTING_MIN_TRIGGERS = _scout._LISTING_MIN_TRIGGERS
_LISTING_YEARS = _scout._LISTING_YEARS
_reconciled_stats_for_strategy = _scout._reconciled_stats_for_strategy


# ── Synthetic bar builders ────────────────────────────────────────────────────

def _make_bars_trending(n: int = 1300, seed: int = 1) -> list[dict]:
    """Generate n daily bars with a slow uptrend + noise. ~5y of trading days.

    Enough length to give Donchian / SMA-cross detectors a healthy number of
    triggers (>20) so the min-sample filter doesn't strip them.
    """
    rng = random.Random(seed)
    price = 100.0
    bars = []
    for i in range(n):
        # Slow drift up + AR(1) noise + occasional vol spikes
        drift = 0.0008
        noise = rng.gauss(0, 0.015)
        if i % 90 == 0:
            noise += rng.choice([-0.04, 0.04])
        price *= (1.0 + drift + noise)
        h = price * (1 + abs(rng.gauss(0, 0.005)))
        l = price * (1 - abs(rng.gauss(0, 0.005)))
        bars.append({
            "c": price,
            "o": price,
            "h": h,
            "l": l,
            "v": 1_000_000,
            "t": f"2021-01-01T00:00:00Z",  # detectors don't depend on dates
        })
    return bars


def _make_bars_choppy(n: int = 1300, seed: int = 7) -> list[dict]:
    """Sideways with periodic mean reversion — exercises RSI / Bollinger detectors."""
    rng = random.Random(seed)
    base = 100.0
    bars = []
    for i in range(n):
        # Sine wave + noise → repeatable squeezes and oversold readings
        sine = math.sin(i / 22.0) * 6.0
        noise = rng.gauss(0, 0.6)
        price = base + sine + noise
        bars.append({
            "c": price,
            "o": price,
            "h": price + abs(rng.gauss(0, 0.3)),
            "l": price - abs(rng.gauss(0, 0.3)),
            "v": 1_000_000,
            "t": f"2021-01-01T00:00:00Z",
        })
    return bars


# ── Reconciliation: listing helper == direct run_backtest ─────────────────────

SYMBOLS = ["TSLA", "NVDA", "AAPL", "SPY", "BTC/USD"]

# Strategies known to be registered with detectors in strategy_backtest._DETECTORS
# Pick one that reliably fires >20 times on the synthetic noisy bars.
# Donchian 20-day breakout fires multiple times per year on choppy trending
# data — easy to get 30-50 triggers across ~5y of synthetic bars.
RECONCILE_STRATEGY = "donchian_breakout"


@pytest.mark.parametrize("symbol", SYMBOLS)
def test_listing_matches_past_triggers(symbol: str) -> None:
    """For each named symbol, the listing helper must produce numbers that
    reconcile with a direct run_backtest call within the spec tolerances.

    Same function under the hood means in practice they should be EXACT —
    we still assert against the spec tolerances (Sharpe ±0.1, win ±1%,
    avg_return ±0.1%, triggers exact) to guard against a future refactor
    accidentally re-introducing a parallel implementation.
    """
    bars = _make_bars_trending(n=1300, seed=hash(symbol) & 0xFFFF)

    listing = _reconciled_stats_for_strategy(RECONCILE_STRATEGY, symbol, bars)
    past = run_backtest(
        RECONCILE_STRATEGY,
        symbol,
        bars,
        years_requested=_LISTING_YEARS,
        hold_days=_LISTING_HOLD_DAYS,
    )

    if past.trigger_count < _LISTING_MIN_TRIGGERS:
        # Synthetic series didn't produce enough triggers — skip rather than
        # assert on a None listing. Real-symbol assertions live in the
        # integration test layer; this test exercises the wiring.
        assert listing is None
        pytest.skip(
            f"{symbol}: synthetic series produced {past.trigger_count} triggers "
            f"(<{_LISTING_MIN_TRIGGERS}); listing correctly filtered"
        )

    assert listing is not None, f"{symbol}: listing should not be None when N≥20"

    # Trigger count: MUST be exact equality (both surfaces call the same fn)
    assert listing["trigger_count"] == past.trigger_count, (
        f"{symbol}: listing triggers {listing['trigger_count']} != "
        f"past triggers {past.trigger_count}"
    )

    # Sharpe: ±0.1
    past_sharpe = float(past.sharpe or 0.0)
    assert abs(listing["sharpe"] - past_sharpe) <= 0.1, (
        f"{symbol}: Sharpe diff {abs(listing['sharpe'] - past_sharpe):.3f} > 0.1"
    )

    # Win rate: listing in percent (0-100), past in decimal (0-1)
    past_win_pct = float(past.win_rate or 0.0) * 100.0
    assert abs(listing["win_rate_pct"] - past_win_pct) <= 1.0, (
        f"{symbol}: win-rate diff {abs(listing['win_rate_pct'] - past_win_pct):.3f}% > 1%"
    )

    # Avg return: listing in percent (e.g. -1.34), past in decimal (e.g. -0.0134)
    past_avg_pct = float(past.avg_return or 0.0) * 100.0
    assert abs(listing["avg_return_pct"] - past_avg_pct) <= 0.1, (
        f"{symbol}: avg-return diff "
        f"{abs(listing['avg_return_pct'] - past_avg_pct):.3f}% > 0.1%"
    )


# ── Min-sample filter ─────────────────────────────────────────────────────────

def test_min_sample_filter_excludes_low_trigger_strategies() -> None:
    """Strategies with <20 triggers must return None from the listing helper.

    Use a very short bar series so any detector fires fewer than 20 times.
    """
    short_bars = _make_bars_trending(n=400, seed=999)  # ~1.5y
    result = _reconciled_stats_for_strategy("trend_follow_50_200", "TEST", short_bars)
    if result is not None:
        # If somehow ≥20 triggers fired on the short series, just verify the
        # min-sample check did apply (trigger_count must be >= 20).
        assert result["trigger_count"] >= _LISTING_MIN_TRIGGERS, (
            f"min-sample filter not enforced: result has {result['trigger_count']} triggers"
        )


def test_min_sample_threshold_value() -> None:
    """Spec calls for min 20 triggers. Lock the constant so a future drive-by
    edit can't silently change it back to 3."""
    assert _LISTING_MIN_TRIGGERS == 20


def test_listing_parameters_match_past_triggers_default() -> None:
    """Listing MUST run the same lookback / hold as the Past Triggers panel
    default (5y, 30d). If the panel default ever changes, this assertion will
    fire to prompt the listing constants to be updated in lockstep."""
    assert _LISTING_YEARS == 5, "Past Triggers default is 5y — listing must match"
    assert _LISTING_HOLD_DAYS == 30, "Past Triggers default hold is 30d — listing must match"


# ── Payload shape ─────────────────────────────────────────────────────────────

def test_listing_payload_has_avg_return_pct_field() -> None:
    """SHIP 4 adds avg_return_pct to the listing payload. Frontend depends on it."""
    bars = _make_bars_trending(n=1300, seed=42)
    result = _reconciled_stats_for_strategy("donchian_breakout", "TSLA", bars)
    if result is None:
        pytest.skip("not enough triggers in synthetic series")
    assert "avg_return_pct" in result
    assert "sharpe" in result
    assert "win_rate_pct" in result
    assert "trigger_count" in result
    assert "trades_per_year" in result
    assert "composite_score" in result
    # avg_return_pct is a signed percent (e.g. -1.34, not -0.0134)
    # Sanity check: it must be a finite number within a reasonable range.
    assert -100.0 < result["avg_return_pct"] < 500.0
