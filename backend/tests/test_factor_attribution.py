"""Phase 6 — portfolio factor attribution math tests.

Brock spec acceptance:
  - gross=$100k, beta=1.0, SPY +2% -> beta_pnl = $2,000
  - gross=$100k, beta=0.5, SPY +2% -> beta_pnl = $1,000
  - alpha + beta == total_pnl within 1 cent of rounding
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock as _MM, patch

# conftest already adds backend/ to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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


# conftest.py stubs out app.* — bypass by loading source files directly.
# Patch in BotSignal which conftest doesn't pre-stub.
_bots_stub = sys.modules.get("app.db.models.bots")
if _bots_stub is not None and not hasattr(_bots_stub, "BotSignal"):
    _bots_stub.BotSignal = _MM(name="BotSignal")

_factor_service = _load_module_from_path(
    "app.services.factor_attribution_service",
    "app/services/factor_attribution_service.py",
)
parse_window = _factor_service.parse_window
compute_factor_attribution = _factor_service.compute_factor_attribution

# Wire onto stub so patch("app.services.factor_attribution_service.X") works.
_services_mod = sys.modules.get("app.services")
if _services_mod is not None:
    _services_mod.factor_attribution_service = _factor_service


# ── Direct formula tests (no DB) ──────────────────────────────────────────────

def _beta_pnl_cents(gross_cents: float, beta: float, spy_ret: float) -> float:
    """The exact formula the service uses."""
    return beta * spy_ret * gross_cents


def test_beta_pnl_gross_100k_beta_1_spy_2pct():
    gross = 100_000 * 100  # $100k in cents
    bp = _beta_pnl_cents(gross, 1.0, 0.02)
    assert round(bp) == 200_000, f"expected $2,000 = 200000c, got {bp}"


def test_beta_pnl_gross_100k_beta_05_spy_2pct():
    gross = 100_000 * 100
    bp = _beta_pnl_cents(gross, 0.5, 0.02)
    assert round(bp) == 100_000, f"expected $1,000 = 100000c, got {bp}"


def test_alpha_plus_beta_equals_total_within_1_cent():
    """alpha_pnl_cents = total_pnl_cents - beta_pnl_cents -> identity."""
    total = 1_234_500
    beta_pnl = round(0.78 * 0.013 * 125_000_000)
    alpha = total - beta_pnl
    assert abs((alpha + beta_pnl) - total) <= 1


def test_beta_pnl_negative_when_spy_down():
    gross = 200_000 * 100
    bp = _beta_pnl_cents(gross, 1.2, -0.015)
    assert bp == 1.2 * -0.015 * gross
    assert bp < 0


def test_beta_pnl_zero_gross_returns_zero():
    assert _beta_pnl_cents(0, 1.0, 0.05) == 0.0


# ── Beta map tests ────────────────────────────────────────────────────────────

def test_beta_map_known_etfs():
    from strategy_lab.core.beta_map import get_beta
    assert get_beta("SPY") == 1.00
    assert get_beta("QQQ") == 1.15
    assert get_beta("IWM") == 1.20
    assert get_beta("GLD") == 0.00
    assert get_beta("TLT") == -0.30


def test_beta_map_crypto():
    from strategy_lab.core.beta_map import get_beta
    assert get_beta("BTC") == 0.50
    assert get_beta("ETH") == 0.60
    assert get_beta("BTC/USD") == 0.50
    assert get_beta("ETH/USD") == 0.60


def test_beta_map_unknown_defaults_to_1():
    from strategy_lab.core.beta_map import get_beta, DEFAULT_BETA
    assert get_beta("ZZZNOTAREALSYMBOL") == DEFAULT_BETA == 1.0
    assert get_beta("") == DEFAULT_BETA


def test_beta_map_case_insensitive():
    from strategy_lab.core.beta_map import get_beta
    assert get_beta("spy") == get_beta("SPY") == 1.00


# ── Window parsing ────────────────────────────────────────────────────────────

def test_parse_window_known_values():
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    s7, lbl7 = parse_window("7d")
    assert lbl7 == "7d"
    assert (now - s7) >= timedelta(days=6, hours=23)

    s30, lbl30 = parse_window("30d")
    assert lbl30 == "30d"

    s90, lbl90 = parse_window("90d")
    assert lbl90 == "90d"

    sytd, lblytd = parse_window("ytd")
    assert lblytd == "ytd"
    assert sytd.month == 1 and sytd.day == 1

    sx, lblx = parse_window("garbage")
    assert lblx == "30d"


# ── End-to-end with mocked DB and SPY ─────────────────────────────────────────

class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_k):
        return self

    def order_by(self, *_a, **_k):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return self._rows


class _FakeSession:
    """Cycle through pre-canned query results by model class."""
    def __init__(self, by_model: dict):
        self._by_model = by_model

    def query(self, model):
        return _FakeQuery(self._by_model.get(model, []))


def _make_alloc(id_: int, user_id: int = 1, profile_id: int = 10):
    class A:
        pass
    a = A()
    a.id = id_
    a.user_id = user_id
    a.profile_id = profile_id
    return a


def _make_profile(id_: int = 10, asset_class: str = "stock"):
    class P:
        pass
    p = P()
    p.id = id_
    p.asset_class = asset_class
    return p


def _make_position(symbol: str, qty: float, avg_cost_cents: float, side: str = "long",
                   allocation_id: int = 1, position_id: int = 1, closed: bool = False):
    from datetime import datetime, timezone
    class Pos:
        pass
    p = Pos()
    p.id = position_id
    p.allocation_id = allocation_id
    p.symbol = symbol
    p.qty = qty
    p.avg_cost_cents = avg_cost_cents
    p.side = side
    p.opened_at = datetime.now(timezone.utc).replace(tzinfo=None)
    p.closed_at = (datetime.now(timezone.utc).replace(tzinfo=None) if closed else None)
    p.quarantined_at = None
    return p


def test_compute_factor_attribution_no_allocations_returns_zeros():
    """User with no allocations -> all-zero shape."""
    from app.db.models.bots import BotAllocation

    db = _FakeSession({BotAllocation: []})
    out = compute_factor_attribution(db, user_id=999, window="30d")
    assert out["window"] == "30d"
    assert out["total_pnl_cents"] == 0
    assert out["beta_pnl_cents"] == 0
    assert out["alpha_pnl_cents"] == 0
    assert out["portfolio_beta"] == 0.0
    assert out["gross_exposure_cents"] == 0
    assert out["net_exposure_cents"] == 0
    assert out["top_contributors"] == []
    assert out["top_detractors"] == []


def test_compute_factor_attribution_single_spy_position_beta1_spy_up_2pct():
    """Single open SPY position, gross=$100k, beta=1.0, SPY +2% -> beta_pnl == $2,000."""
    from app.db.models.bots import BotAllocation, BotProfile, BotPosition

    alloc = _make_alloc(id_=1, user_id=1, profile_id=10)
    profile = _make_profile(id_=10, asset_class="stock")
    # $100k = 10,000,000 cents -> 100 shares × 100,000 cents/share
    pos = _make_position("SPY", qty=100.0, avg_cost_cents=100_000.0,
                         allocation_id=1, position_id=1, closed=False)

    db = _FakeSession({
        BotAllocation: [alloc],
        BotProfile: [profile],
        BotPosition: [pos],
    })

    with patch("app.services.factor_attribution_service.fetch_spy_return", return_value=0.02):
        out = compute_factor_attribution(db, user_id=1, window="30d")

    assert out["gross_exposure_cents"] == 10_000_000  # $100k in cents
    assert out["net_exposure_cents"] == 10_000_000
    assert out["portfolio_beta"] == 1.0
    # 1.0 × 0.02 × 10_000_000 = 200_000 cents = $2,000
    assert out["beta_pnl_cents"] == 200_000


def test_compute_factor_attribution_beta_zero_no_beta_pnl():
    """GLD has beta 0.0 -> no beta-pnl regardless of SPY move."""
    from app.db.models.bots import BotAllocation, BotProfile, BotPosition

    alloc = _make_alloc(id_=1)
    profile = _make_profile(id_=10, asset_class="stock")
    pos = _make_position("GLD", qty=100.0, avg_cost_cents=100_000.0,
                         allocation_id=1, position_id=1, closed=False)

    db = _FakeSession({
        BotAllocation: [alloc],
        BotProfile: [profile],
        BotPosition: [pos],
    })

    with patch("app.services.factor_attribution_service.fetch_spy_return", return_value=0.02):
        out = compute_factor_attribution(db, user_id=1, window="30d")

    assert out["portfolio_beta"] == 0.0
    assert out["beta_pnl_cents"] == 0


def test_alpha_plus_beta_reconstructs_total_in_compute():
    """End-to-end identity: alpha + beta == total (within 1 cent)."""
    from app.db.models.bots import BotAllocation, BotProfile, BotPosition

    alloc = _make_alloc(id_=1)
    profile = _make_profile(id_=10, asset_class="stock")
    # NVDA beta=1.65 gives a non-trivial beta P&L
    pos = _make_position("NVDA", qty=50.0, avg_cost_cents=50_000.0,
                         allocation_id=1, position_id=1, closed=False)

    db = _FakeSession({
        BotAllocation: [alloc],
        BotProfile: [profile],
        BotPosition: [pos],
    })

    with patch("app.services.factor_attribution_service.fetch_spy_return", return_value=0.012):
        out = compute_factor_attribution(db, user_id=1, window="30d")

    assert abs((out["alpha_pnl_cents"] + out["beta_pnl_cents"]) - out["total_pnl_cents"]) <= 1
